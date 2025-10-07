"""End-to-end tests covering agent interactions via the event bus."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from emotion_diary.agents import (
    CheckinWriter,
    Dedup,
    Delete,
    Export,
    Notifier,
    PetRender,
    Router,
)
from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import SQLiteAdapter, Storage


def test_checkin_export_delete_flow(tmp_path: Path):
    """Ensure the check-in, export, and delete flow works end-to-end."""

    async def _run():
        """Drive the complete agent sequence using in-memory storage."""
        bus = EventBus()
        storage = Storage(SQLiteAdapter(":memory:"))
        export_dir = tmp_path / "exports"

        Dedup(bus)
        Router(bus, storage)
        CheckinWriter(bus, storage)
        PetRender(bus)
        Notifier(bus)
        Export(bus, storage, export_dir)
        Delete(bus, storage)

        responses: list[dict] = []

        def capture_response(event):
            """Collect responses emitted during the flow."""
            responses.append(event.payload)

        bus.subscribe("tg.response", capture_response)

        now = datetime.now(UTC)
        await bus.publish(
            "tg.update",
            {
                "chat_id": 1001,
                "text": "/checkin good",
                "update_id": 1,
                "ts": now,
            },
        )
        ident = storage.get_or_create_ident(1001)
        entries = storage.list_entries(ident.pid)
        assert len(entries) == 1
        assert entries[0].mood == 1
        assert any("Записал настроение" in resp["text"] for resp in responses)

        await bus.publish(
            "tg.update",
            {
                "chat_id": 1001,
                "text": "/checkin good",
                "update_id": 1,
                "ts": now + timedelta(minutes=1),
            },
        )
        assert len(storage.list_entries(ident.pid)) == 1

        storage.ensure_user_record(ident.pid, notify_hour=now.hour)
        assert (ident.pid, 1001) in storage.due_users(now.hour)

        responses.clear()
        await bus.publish("export.request", {"pid": ident.pid, "chat_id": 1001})
        export_files = list(export_dir.glob("*.csv"))
        assert export_files, "export file must be created"
        assert any(
            ("text" in resp and "Готов экспорт данных" in resp["text"])
            or ("caption" in resp and "Готов экспорт данных" in resp["caption"])
            for resp in responses
        )

        responses.clear()
        await bus.publish("delete.request", {"pid": ident.pid, "chat_id": 1001})
        assert storage.list_entries(ident.pid) == []
        assert any("данные удалены" in resp["text"].lower() for resp in responses)

    asyncio.run(_run())


def test_notifier_ping_request_keyboard():
    """Verify that notifier produces correct inline keyboard for ping events."""

    async def _run():
        """Emit a ping request and inspect the generated keyboard."""
        bus = EventBus()
        Notifier(bus)

        responses: list[dict] = []

        def capture(event):
            """Collect outgoing responses for assertions."""
            responses.append(event.payload)

        bus.subscribe("tg.response", capture)

        await bus.publish("ping.request", {"chat_id": 4242})

        assert responses, "Notifier must emit tg.response"
        reply_markup = responses[0].get("reply_markup")
        assert reply_markup, "reply_markup is required for ping.request"
        keyboard = reply_markup.get("inline_keyboard")
        assert keyboard and isinstance(keyboard, list)
        buttons = keyboard[0]
        assert [btn["callback_data"] for btn in buttons] == [
            "mood:+1",
            "mood:0",
            "mood:-1",
        ]
        assert [btn["text"] for btn in buttons] == ["🙂/+1", "😐/0", "🙁/-1"]

    asyncio.run(_run())


def test_router_handles_callback_mood():
    """Ensure router translates callback queries into mood check-ins."""

    async def _run():
        """Simulate callback payload handling by the router."""
        bus = EventBus()
        storage = Storage(SQLiteAdapter(":memory:"))
        router = Router(bus, storage)

        captured: list[dict] = []

        async def capture(event):
            """Collect emitted check-in payloads."""
            captured.append(event.payload)

        bus.subscribe("checkin.save", capture)

        event = Event(
            name="tg.update",
            payload={"chat_id": 7, "callback_data": "mood:+1"},
            metadata={"dedup_passed": True},
        )

        await router.handle_update(event)

        assert captured, "Router must convert callback into checkin.save"
        assert captured[0]["mood"] == 1

    asyncio.run(_run())
