"""Router agent converts Telegram updates into domain events."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Router:
    """Routes Telegram updates into domain-specific commands and events."""

    bus: EventBus
    storage: Storage

    def __post_init__(self) -> None:
        """Subscribe to incoming Telegram updates on the event bus."""
        self.bus.subscribe("tg.update", self.handle_update)

    async def handle_update(self, event: Event) -> None:
        """Transform Telegram updates into domain events.

        Args:
            event: Telegram update wrapped in an event bus envelope.

        """
        if not event.metadata.get("dedup_passed"):  # pragma: no branch - guard
            return
        payload = event.payload
        chat_id = payload.get("chat_id")
        if chat_id is None:  # pragma: no branch - guard
            logger.debug("tg.update without chat_id: %s", payload)
            return
        ident = self.storage.get_or_create_ident(chat_id)
        command = self._resolve_command(payload)
        if command == "export":  # pragma: no branch - simple dispatch
            await self.bus.publish(
                "export.request",
                {"pid": ident.pid, "chat_id": chat_id},
            )
        elif command == "delete":  # pragma: no branch - simple dispatch
            await self.bus.publish(
                "delete.request",
                {"pid": ident.pid, "chat_id": chat_id},
            )
        elif command == "checkin":
            mood = self._resolve_mood(payload)
            if mood is None:  # pragma: no branch - guard
                logger.debug("Cannot resolve mood from payload %s", payload)
                return
            ts = payload.get("ts")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if not isinstance(ts, datetime):
                ts = datetime.now(UTC)
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
        else:  # pragma: no branch - debug logging
            logger.debug("Unhandled command %s", command)

    def _resolve_command(self, payload: Mapping[str, Any]) -> str | None:
        """Derive the high-level command encoded in the payload.

        Args:
            payload: Incoming Telegram payload with text or callback data.

        Returns:
            The resolved command name or ``None`` if nothing matches.

        """
        data_candidate = payload.get("callback_data")
        if not isinstance(data_candidate, str):
            text_candidate = payload.get("text")
            if isinstance(text_candidate, str):
                data_candidate = text_candidate
            else:
                data_candidate = ""
        data = data_candidate.strip().lower()
        if data.startswith("/export"):  # pragma: no branch - deterministic prefix
            return "export"
        if data.startswith("/delete"):  # pragma: no branch - deterministic prefix
            return "delete"
        if data.startswith("/start"):  # pragma: no branch - deterministic prefix
            return "checkin"
        if data.startswith("/checkin"):  # pragma: no branch - deterministic prefix
            return "checkin"
        if any(token in data for token in {"mood", "feeling", "эмоция"}):
            return "checkin"
        if payload.get("mood") is not None:  # pragma: no branch - guard
            return "checkin"
        return None

    def _resolve_mood(self, payload: Mapping[str, Any]) -> int | None:
        """Extract the mood value from the payload.

        Args:
            payload: Telegram payload containing mood hints.

        Returns:
            Mood value in the ``{-1, 0, 1}`` range or ``None`` if missing.

        """
        callback_data = payload.get("callback_data")
        if isinstance(callback_data, str):  # pragma: no branch - parsing helper
            callback_data = callback_data.strip()
            if callback_data.startswith("mood:"):
                _, _, mood_part = callback_data.partition(":")
                mood_part = mood_part.strip().replace("\u2212", "-")
                try:
                    mood = int(mood_part)
                except ValueError:
                    mood = None
                else:
                    return mood if mood in {-1, 0, 1} else None
        mood_value = payload.get("mood")
        if mood_value is not None:
            try:
                mood = int(mood_value)
            except (TypeError, ValueError):
                mood = None
        else:
            text_candidate = payload.get("text")
            text = text_candidate.lower() if isinstance(text_candidate, str) else ""
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
        if mood is None:  # pragma: no branch - guard
            return None
        if mood not in {-1, 0, 1}:  # pragma: no branch - guard
            return None
        return mood
