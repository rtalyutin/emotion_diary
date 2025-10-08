"""End-to-end tests covering agent interactions via the event bus."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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


Responses = list[dict[str, Any]]


def create_agent_environment(
    tmp_path: Path,
) -> tuple[
    EventBus,
    Storage,
    Path,
    Responses,
]:
    """Instantiate agents and capture outgoing responses for assertions."""

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

    responses: Responses = []

    def capture_response(event: Event) -> None:
        """Append emitted tg.response payloads for later assertions."""
        responses.append(event.payload)

    bus.subscribe("tg.response", capture_response)
    return bus, storage, export_dir, responses


async def perform_checkin(
    bus: EventBus,
    storage: Storage,
    responses: Responses,
    *,
    chat_id: int,
    now: datetime,
) -> int:
    """Publish a mood check-in and ensure it is persisted and acknowledged."""

    await bus.publish(
        "tg.update",
        {
            "chat_id": chat_id,
            "text": "/checkin good",
            "update_id": 1,
            "ts": now,
        },
    )
    ident = storage.get_or_create_ident(chat_id)
    entries = storage.list_entries(ident.pid)
    assert len(entries) == 1
    assert entries[0].mood == 1
    assert any("Записал настроение" in resp["text"] for resp in responses)
    return ident.pid


async def verify_deduplication(
    bus: EventBus, storage: Storage, *, pid: int, chat_id: int, now: datetime
) -> None:
    """Emit a duplicate update and ensure it is ignored by the flow."""

    await bus.publish(
        "tg.update",
        {
            "chat_id": chat_id,
            "text": "/checkin good",
            "update_id": 1,
            "ts": now + timedelta(minutes=1),
        },
    )
    assert len(storage.list_entries(pid)) == 1


async def verify_export(
    bus: EventBus,
    storage: Storage,
    responses: Responses,
    export_dir: Path,
    *,
    pid: int,
    chat_id: int,
    now: datetime,
) -> None:
    """Request export and ensure files and notifications are produced."""

    storage.ensure_user_record(pid, notify_hour=now.hour)
    assert (pid, chat_id) in storage.due_users(now.hour)

    responses.clear()
    await bus.publish("export.request", {"pid": pid, "chat_id": chat_id})
    export_files = list(export_dir.glob("*.csv"))
    assert export_files, "export file must be created"
    assert any(
        ("text" in resp and "Готов экспорт данных" in resp["text"])
        or ("caption" in resp and "Готов экспорт данных" in resp["caption"])
        for resp in responses
    )


async def verify_delete(
    bus: EventBus,
    storage: Storage,
    responses: Responses,
    *,
    pid: int,
    chat_id: int,
) -> None:
    """Delete stored data and check that records and notifications are cleared."""

    responses.clear()
    await bus.publish("delete.request", {"pid": pid, "chat_id": chat_id})
    assert storage.list_entries(pid) == []
    assert any("данные удалены" in resp["text"].lower() for resp in responses)


async def exercise_checkin_export_delete_flow(
    bus: EventBus,
    storage: Storage,
    responses: Responses,
    export_dir: Path,
    *,
    chat_id: int,
    now: datetime,
) -> None:
    """Drive the check-in, export, and delete path end-to-end."""

    pid = await perform_checkin(
        bus,
        storage,
        responses,
        chat_id=chat_id,
        now=now,
    )
    await verify_deduplication(bus, storage, pid=pid, chat_id=chat_id, now=now)
    await verify_export(
        bus,
        storage,
        responses,
        export_dir,
        pid=pid,
        chat_id=chat_id,
        now=now,
    )
    await verify_delete(
        bus,
        storage,
        responses,
        pid=pid,
        chat_id=chat_id,
    )


def test_checkin_export_delete_flow(tmp_path: Path) -> None:
    """Ensure the check-in, export, and delete flow works end-to-end."""

    bus, storage, export_dir, responses = create_agent_environment(tmp_path)
    now = datetime.now(UTC)
    chat_id = 1001

    asyncio.run(
        exercise_checkin_export_delete_flow(
            bus,
            storage,
            responses,
            export_dir,
            chat_id=chat_id,
            now=now,
        )
    )


def test_notifier_ping_request_keyboard() -> None:
    """Verify that notifier produces correct inline keyboard for ping events."""

    async def _run() -> None:
        """Emit a ping request and inspect the generated keyboard."""
        bus = EventBus()
        Notifier(bus)

        responses: list[dict[str, Any]] = []

        def capture(event: Event) -> None:
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


def test_router_handles_callback_mood() -> None:
    """Ensure router translates callback queries into mood check-ins."""

    async def _run() -> None:
        """Simulate callback payload handling by the router."""
        bus = EventBus()
        storage = Storage(SQLiteAdapter(":memory:"))
        router = Router(bus, storage)

        captured: list[dict[str, Any]] = []

        async def capture(event: Event) -> None:
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
