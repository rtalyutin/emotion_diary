from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from emotion_diary.agents import CheckinWriter, Dedup, Notifier, Router
from emotion_diary.bot.transport import (
    TelegramResponder,
    WebhookServer,
    run_polling,
)
from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import SQLiteAdapter, Storage


class FakeTelegramAPI:
    def __init__(self, updates: list[dict]):
        self._updates = list(updates)
        self.sent: list[tuple[str, dict]] = []
        self.offsets: list[int | None] = []
        self.sent_event = asyncio.Event()

    async def get_updates(self, *, offset=None, timeout=None, allowed_updates=None):  # noqa: D401
        self.offsets.append(offset)
        result = list(self._updates)
        self._updates.clear()
        return result

    async def send_message(self, chat_id, text, **extra):
        self.sent.append(("sendMessage", {"chat_id": chat_id, "text": text, **extra}))
        self.sent_event.set()

    async def send_photo(self, chat_id, photo, **extra):
        self.sent.append(("sendPhoto", {"chat_id": chat_id, "photo": photo, **extra}))
        self.sent_event.set()

    async def call_method(self, method, params=None, *, files=None):
        payload = {"params": dict(params or {})}
        if files is not None:
            payload["files"] = files
        self.sent.append((method, payload))
        self.sent_event.set()


def test_polling_transport_integration(tmp_path):
    import pytest

    async def _run():
        bus = EventBus()
        storage = Storage(SQLiteAdapter(":memory:"))
        Dedup(bus)
        Router(bus, storage)
        CheckinWriter(bus, storage)
        Notifier(bus)

        updates = [
            {
                "update_id": 101,
                "message": {
                    "message_id": 1,
                    "date": int(datetime.now(timezone.utc).timestamp()),
                    "chat": {"id": 555},
                    "text": "/checkin good",
                },
            }
        ]
        api = FakeTelegramAPI(updates)
        TelegramResponder(bus, api)  # subscribe responses

        task = asyncio.create_task(run_polling(bus, api, poll_timeout=0, idle_delay=0.01))
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

        assert api.offsets
        assert api.offsets[0] is None
        if len(api.offsets) > 1:
            assert api.offsets[1] == 102

    asyncio.run(_run())


def test_telegram_responder_sends_photo():
    async def _run():
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


def test_webhook_server_validates_secret_and_publishes():
    async def _run():
        bus = EventBus()
        received: list[Event] = []

        async def capture(event: Event) -> None:
            received.append(event)

        bus.subscribe("tg.update", capture)
        server = WebhookServer("127.0.0.1", 0, "secret", bus)

        payload = {
            "update_id": 77,
            "message": {
                "chat": {"id": 1},
                "date": int(datetime.now(timezone.utc).timestamp()),
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
