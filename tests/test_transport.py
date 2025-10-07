"""Integration-style tests for the Telegram transport components."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from emotion_diary.agents import CheckinWriter, Dedup, Export, Notifier, Router
from emotion_diary.bot.transport import (
    TelegramResponder,
    WebhookServer,
    _extract_callback_fields,
    _extract_message_fields,
    normalize_update,
    run_polling,
)
from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import SQLiteAdapter, Storage


@dataclass
class PollingEnvironment:
    """Container describing dependencies used during polling integration tests."""

    bus: EventBus
    storage: Storage
    api: FakeTelegramAPI
    captured_updates: list[dict[str, Any]]
    message_date: int
    chat_id: int


class FakeTelegramAPI:
    """In-memory stand-in for the Telegram API used during tests."""

    def __init__(self, updates: list[dict[str, Any]]) -> None:
        """Store prepared updates and initialise tracking attributes."""
        self._updates: list[dict[str, Any]] = list(updates)
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.offsets: list[int | None] = []
        self.sent_event = asyncio.Event()

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int | None = None,
        allowed_updates: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return queued updates while recording offsets."""
        self.offsets.append(offset)
        result = list(self._updates)
        self._updates.clear()
        return result

    async def send_message(self, chat_id: int, text: str, **extra: Any) -> None:
        """Record outgoing ``sendMessage`` requests."""
        self.sent.append(("sendMessage", {"chat_id": chat_id, "text": text, **extra}))
        self.sent_event.set()

    async def send_photo(self, chat_id: int, photo: str, **extra: Any) -> None:
        """Record outgoing ``sendPhoto`` requests."""
        self.sent.append(("sendPhoto", {"chat_id": chat_id, "photo": photo, **extra}))
        self.sent_event.set()

    async def call_method(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> None:
        """Record generic API calls, including uploaded files."""
        payload: dict[str, Any] = {"params": dict(params or {})}
        if files is not None:
            payload["files"] = files
        self.sent.append((method, payload))
        self.sent_event.set()


async def setup_polling_environment(tmp_path: Path) -> PollingEnvironment:
    """Initialise the event bus, storage, agents, and Telegram API doubles."""

    bus = EventBus()
    storage = Storage(SQLiteAdapter(":memory:"))
    Dedup(bus)
    Router(bus, storage)
    CheckinWriter(bus, storage)
    Export(bus, storage, tmp_path)
    Notifier(bus)

    captured_updates: list[dict[str, Any]] = []

    def capture_update(event: Event) -> None:
        captured_updates.append(dict(event.payload))

    bus.subscribe("tg.update", capture_update)

    message_date = int(datetime.now(UTC).timestamp())
    chat_id = 555
    updates = [
        {
            "update_id": 101,
            "message": {
                "message_id": 1,
                "date": message_date,
                "chat": {"id": chat_id},
                "text": "/checkin good",
            },
        }
    ]

    api = FakeTelegramAPI(updates)
    TelegramResponder(bus, api)

    return PollingEnvironment(
        bus=bus,
        storage=storage,
        api=api,
        captured_updates=captured_updates,
        message_date=message_date,
        chat_id=chat_id,
    )


async def run_polling_cycle(env: PollingEnvironment) -> None:
    """Drive the polling coroutine until the first response is produced."""

    task = asyncio.create_task(
        run_polling(env.bus, env.api, poll_timeout=0, idle_delay=0.01)
    )
    try:
        await asyncio.wait_for(env.api.sent_event.wait(), timeout=1)
        await asyncio.sleep(0.05)
    finally:
        task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def assert_polling_response(env: PollingEnvironment):
    """Validate that check-in processing stored data and responded."""

    ident = env.storage.get_or_create_ident(env.chat_id)
    row = env.storage.adapter.fetchone(
        "SELECT COUNT(*) as cnt, MAX(mood) as mood FROM entries WHERE pid=?",
        (ident.pid,),
    )
    assert row["cnt"] == 1
    assert row["mood"] == 1

    assert env.api.sent, "response must be sent via Telegram API"
    method, payload = env.api.sent[0]
    assert method == "sendMessage"
    assert payload["chat_id"] == env.chat_id
    assert "Записал" in payload["text"]

    assert env.api.offsets
    assert env.api.offsets[0] is None
    if len(env.api.offsets) > 1:
        assert env.api.offsets[1] == 102

    assert env.captured_updates, "normalize_update must emit at least one event"
    normalized = env.captured_updates[0]
    assert "ts" in normalized
    ts = normalized["ts"]
    assert isinstance(ts, datetime)
    assert ts.tzinfo is UTC
    assert int(ts.timestamp()) == env.message_date

    return ident


async def assert_export_document(env: PollingEnvironment, ident) -> None:
    """Publish an export request and verify Telegram document delivery."""

    env.api.sent_event.clear()
    await env.bus.publish(
        "export.request",
        {"pid": ident.pid, "chat_id": env.chat_id},
    )
    await asyncio.wait_for(env.api.sent_event.wait(), timeout=1)

    method, payload = env.api.sent[-1]
    assert method == "sendDocument"
    params = payload["params"]
    assert params["chat_id"] == env.chat_id
    assert params["caption"] == "Готов экспорт данных. Файл во вложении."
    files = payload["files"]
    assert "document" in files
    filename, content, mime = files["document"]
    assert filename.endswith(".csv")
    assert mime == "text/csv"
    assert b"ts,mood,note" in content


@pytest.mark.asyncio
async def test_polling_transport_integration(tmp_path: Path) -> None:
    """Verify that polling transport orchestrates agents and responders."""

    env = await setup_polling_environment(tmp_path)
    await run_polling_cycle(env)
    ident = await assert_polling_response(env)
    await assert_export_document(env, ident)


def test_telegram_responder_sends_photo() -> None:
    """Ensure TelegramResponder issues photo requests when sprites are provided."""

    async def _run() -> None:
        """Publish a ``tg.response`` event and assert a photo send call."""
        bus = EventBus()
        api = FakeTelegramAPI([])
        TelegramResponder(bus, api)

        await bus.publish(
            "tg.response",
            {
                "chat_id": 42,
                "text": "Ваш питомец готов",
                "sprite": "sprite_1.png",
            },
        )

        assert api.sent
        method, payload = api.sent[0]
        assert method == "sendPhoto"
        assert payload["chat_id"] == 42
        assert payload["photo"] == "sprite_1.png"
        assert payload["caption"] == "Ваш питомец готов"

    asyncio.run(_run())


def test_telegram_responder_uploads_document(tmp_path: Path) -> None:
    """Ensure TelegramResponder uploads local files for document responses."""

    async def _run() -> None:
        """Publish a ``sendDocument`` response and assert file upload behaviour."""
        bus = EventBus()
        api = FakeTelegramAPI([])
        TelegramResponder(bus, api)

        document = tmp_path / "export.csv"
        document.write_text("ts,mood\n")

        await bus.publish(
            "tg.response",
            {
                "method": "sendDocument",
                "chat_id": 99,
                "document_path": str(document),
                "caption": "Отчёт готов",
            },
        )

        assert api.sent
        method, payload = api.sent[0]
        assert method == "sendDocument"
        assert "files" in payload
        files = payload["files"]
        assert "document" in files
        filename, content, mime = files["document"]
        assert filename == document.name
        assert content == document.read_bytes()
        assert mime == "application/octet-stream"
        params = payload["params"]
        assert params["chat_id"] == 99
        assert params.get("caption") == "Отчёт готов"
        assert "document" not in params

    asyncio.run(_run())


def test_webhook_server_validates_secret_and_publishes() -> None:
    """Ensure webhook requests are validated and routed to the event bus."""

    async def _run() -> None:
        """Run webhook request handling against the in-memory bus."""
        bus = EventBus()
        received: list[Event] = []

        async def capture(event: Event) -> None:
            """Collect published events for assertions."""
            received.append(event)

        bus.subscribe("tg.update", capture)
        server = WebhookServer("127.0.0.1", 0, "secret", bus)

        payload = {
            "update_id": 77,
            "message": {
                "chat": {"id": 1},
                "date": int(datetime.now(UTC).timestamp()),
                "text": "/start",
            },
        }
        headers = {
            "x-telegram-bot-api-secret-token": "secret",
            "content-type": "application/json",
        }
        status, body = await server.process_request(
            "POST", headers, json.dumps(payload).encode("utf-8")
        )
        assert status == 200
        assert body == b"{}"
        assert received
        assert received[0].metadata["transport"] == "webhook"
        assert received[0].payload["chat_id"] == 1

        received.clear()
        status, _ = await server.process_request(
            "POST", {"x-telegram-bot-api-secret-token": "invalid"}, b"{}"
        )
        assert status == 403
        assert not received

    asyncio.run(_run())


def test_extract_message_fields_parses_timestamp_variants() -> None:
    """Ensure message helper normalises chat, text, identifiers, and timestamps."""

    timestamp = int(datetime(2024, 1, 15, tzinfo=UTC).timestamp())
    message = {
        "chat": {"id": 123},
        "text": "hello",
        "message_id": 7,
        "date": timestamp,
    }

    fields = _extract_message_fields(message)

    assert fields["chat_id"] == 123
    assert fields["text"] == "hello"
    assert fields["message_id"] == 7
    assert fields["ts"].tzinfo is UTC
    assert int(fields["ts"].timestamp()) == timestamp

    iso_message = {"date": "2024-02-03T10:11:12+00:00"}
    fields_iso = _extract_message_fields(iso_message)
    assert fields_iso["ts"].isoformat() == "2024-02-03T10:11:12+00:00"


def test_extract_callback_fields_merges_message_and_user() -> None:
    """Ensure callback helper combines callback data, message, and sender info."""

    callback = {
        "data": "payload",
        "message": {"chat": {"id": 777}, "message_id": 99},
        "from": {"id": 42},
    }

    fields = _extract_callback_fields(callback)

    assert fields["callback_data"] == "payload"
    assert fields["chat_id"] == 777
    assert fields["message_id"] == 99
    assert fields["from_id"] == 42


def test_normalize_update_handles_callbacks_and_messages() -> None:
    """Verify ``normalize_update`` orchestrates message and callback helpers."""

    ts = "2024-01-01T00:00:00+00:00"
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 5}, "date": ts},
        "callback_query": {
            "data": "choice",
            "from": {"id": 10},
            "message": {"chat": {"id": 6}, "message_id": 11},
        },
    }

    normalised = normalize_update(update)

    assert normalised["update_id"] == 1
    assert normalised["callback_data"] == "choice"
    assert normalised["from_id"] == 10
    assert normalised["chat_id"] == 6  # callback message overrides original chat
    assert normalised["message_id"] == 11
    assert "ts" in normalised
