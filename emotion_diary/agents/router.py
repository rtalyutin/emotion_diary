"""Router agent converts Telegram updates into domain events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Router:
    bus: EventBus
    storage: Storage

    def __post_init__(self) -> None:
        self.bus.subscribe("tg.update", self.handle_update)

    async def handle_update(self, event: Event) -> None:
        if not event.metadata.get("dedup_passed"):
            return
        payload = event.payload
        chat_id = payload.get("chat_id")
        if chat_id is None:
            logger.debug("tg.update without chat_id: %s", payload)
            return
        ident = self.storage.get_or_create_ident(chat_id)
        command = self._resolve_command(payload)
        if command == "export":
            await self.bus.publish(
                "export.request",
                {"pid": ident.pid, "chat_id": chat_id},
            )
        elif command == "delete":
            await self.bus.publish(
                "delete.request",
                {"pid": ident.pid, "chat_id": chat_id},
            )
        elif command == "checkin":
            mood = self._resolve_mood(payload)
            if mood is None:
                logger.debug("Cannot resolve mood from payload %s", payload)
                return
            ts = payload.get("ts")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if not isinstance(ts, datetime):
                ts = datetime.now(timezone.utc)
            note = payload.get("note") or payload.get("text")
            await self.bus.publish(
                "checkin.save",
                {
                    "pid": ident.pid,
                    "chat_id": chat_id,
                    "mood": mood,
                    "ts": ts,
                    "note": note,
                },
            )
        else:
            logger.debug("Unhandled command %s", command)

    def _resolve_command(self, payload: dict) -> str | None:
        data = payload.get("callback_data") or payload.get("text") or ""
        data = data.strip().lower()
        if data.startswith("/export"):
            return "export"
        if data.startswith("/delete"):
            return "delete"
        if data.startswith("/start"):
            return "checkin"
        if data.startswith("/checkin"):
            return "checkin"
        if any(token in data for token in {"mood", "feeling", "эмоция"}):
            return "checkin"
        if payload.get("mood") is not None:
            return "checkin"
        return None

    def _resolve_mood(self, payload: dict) -> Optional[int]:
        if payload.get("mood") is not None:
            try:
                mood = int(payload["mood"])
            except (TypeError, ValueError):
                mood = None
        else:
            text = (payload.get("text") or "").lower()
            mapping = {
                "bad": -1,
                "meh": 0,
                "ok": 0,
                "good": 1,
                "great": 1,
                "terrible": -1,
            }
            if text.startswith("/checkin"):
                parts = text.split()
                mood = None
                if len(parts) > 1:
                    mood = mapping.get(parts[1])
                    if mood is None:
                        try:
                            mood = int(parts[1])
                        except ValueError:
                            mood = None
            else:
                mood = mapping.get(text.strip())
        if mood is None:
            return None
        if mood not in {-1, 0, 1}:
            return None
        return mood
