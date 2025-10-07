"""Integration-style tests for the Telegram transport components."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from emotion_diary.agents import CheckinWriter, Dedup, Export, Notifier, Router
from emotion_diary.bot.transport import (
    TelegramResponder,
    WebhookServer,
    run_polling,
)
from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import SQLiteAdapter, Storage


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


def test_polling_transport_integration(tmp_path: Path) -> None:
    """Verify that polling transport orchestrates agents and responders."""
    import pytest

    async def _run() -> None:
        """Run the polling workflow end-to-end using in-memory dependencies."""
        bus = EventBus()
        storage = Storage(SQLiteAdapter(":memory:"))
        Dedup(bus)
        Router(bus, storage)
        CheckinWriter(bus, storage)
        Export(bus, storage, tmp_path)
        Notifier(bus)

        updates: list[dict[str, Any]] = [
            {
                "update_id": 101,
                "message": {
                    "message_id": 1,
                    "date": int(datetime.now(UTC).timestamp()),
                    "chat": {"id": 555},
                    "text": "/checkin good",
                },
            }
        ]
        api = FakeTelegramAPI(updates)
        TelegramResponder(bus, api)  # subscribe responses

        task = asyncio.create_task(
            run_polling(bus, api, poll_timeout=0, idle_delay=0.01)
        )
        await asyncio.wait_for(api.sent_event.wait(), timeout=1)
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        ident = storage.get_or_create_ident(555)
        row = storage.adapter.fetchone(
            "SELECT COUNT(*) as cnt, MAX(mood) as mood FROM entries WHERE pid=?",
            (ident.pid,),
        )
        assert row["cnt"] == 1
        assert row["mood"] == 1

        assert api.sent, "response must be sent via Telegram API"
        method, payload = api.sent[0]
        assert method == "sendMessage"
        assert payload["chat_id"] == 555
        assert "Записал" in payload["text"]

        api.sent_event.clear()
        await bus.publish(
            "export.request",
            {"pid": ident.pid, "chat_id": 555},
        )

        method, payload = api.sent[-1]
        assert method == "sendDocument"
        params = payload["params"]
        assert params["chat_id"] == 555
        assert params["caption"] == "Готов экспорт данных. Файл во вложении."
        files = payload["files"]
        assert "document" in files
        filename, content, mime = files["document"]
        assert filename.endswith(".csv")
        assert mime == "text/csv"
        assert b"ts,mood,note" in content

        assert api.offsets
        assert api.offsets[0] is None
        if len(api.offsets) > 1:
            assert api.offsets[1] == 102

    asyncio.run(_run())


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
