"""Agent responsible for persisting mood entries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CheckinWriter:
    bus: EventBus
    storage: Storage

    def __post_init__(self) -> None:
        self.bus.subscribe("checkin.save", self.handle)

    async def handle(self, event: Event) -> None:
        payload = event.payload
        pid = payload.get("pid")
        chat_id = payload.get("chat_id")
        mood = payload.get("mood")
        ts = payload.get("ts")
        if pid is None or chat_id is None:
            logger.debug("Missing pid/chat_id in payload %s", payload)
            return
        if mood not in {-1, 0, 1}:
            logger.debug("Invalid mood %s", mood)
            return
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        note = payload.get("note")
        entry = self.storage.save_entry(pid=pid, ts=ts, mood=mood, note=note)
        await self.bus.publish(
            "checkin.saved",
            {
                "pid": pid,
                "chat_id": chat_id,
                "entry": entry.to_dict(),
            },
        )
