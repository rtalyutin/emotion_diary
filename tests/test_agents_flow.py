from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from emotion_diary.agents import CheckinWriter, Dedup, Delete, Export, Notifier, PetRender, Router
from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import SQLiteAdapter, Storage


def test_checkin_export_delete_flow(tmp_path: Path):
    async def _run():
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
        bus.subscribe("tg.response", lambda event: responses.append(event.payload))

        now = datetime.now(timezone.utc)
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
        assert any("Готов экспорт данных" in resp["text"] for resp in responses)

        responses.clear()
        await bus.publish("delete.request", {"pid": ident.pid, "chat_id": 1001})
        assert storage.list_entries(ident.pid) == []
        assert any("данные удалены" in resp["text"].lower() for resp in responses)

    asyncio.run(_run())


def test_notifier_ping_request_keyboard():
    async def _run():
        bus = EventBus()
        Notifier(bus)

        responses: list[dict] = []

        def capture(event):
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
    async def _run():
        bus = EventBus()
        storage = Storage(SQLiteAdapter(":memory:"))
        router = Router(bus, storage)

        captured: list[dict] = []

        async def capture(event):
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
