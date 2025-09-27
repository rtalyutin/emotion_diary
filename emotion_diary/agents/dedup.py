"""Deduplication agent filters repeated Telegram updates."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Tuple

from emotion_diary.event_bus import Event, EventBus


@dataclass(slots=True)
class Dedup:
    bus: EventBus
    window: timedelta = timedelta(minutes=10)
    _seen: Dict[int, datetime] = field(init=False, default_factory=dict)
    _order: Deque[Tuple[int, datetime]] = field(init=False, default_factory=deque)

    def __post_init__(self) -> None:
        self.bus.subscribe("tg.update", self.handle_update)

    def _prune(self, now: datetime) -> None:
        while self._order and now - self._order[0][1] > self.window:
            update_id, _ = self._order.popleft()
            self._seen.pop(update_id, None)

    async def handle_update(self, event: Event) -> None:
        if event.metadata.get("dedup_passed"):
            return
        update_id = event.payload.get("update_id")
        if update_id is None:
            await self.bus.publish(
                event.name,
                payload=event.payload,
                metadata={**event.metadata, "dedup_passed": True},
            )
            return
        timestamp = event.payload.get("ts")
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        existing = self._seen.get(update_id)
        if existing and timestamp - existing <= self.window:
            return
        self._seen[update_id] = timestamp
        self._order.append((update_id, timestamp))
        self._prune(timestamp)
        await self.bus.publish(
            event.name,
            payload=event.payload,
            metadata={**event.metadata, "dedup_passed": True},
        )

    async def flush(self) -> None:
        """Flush the cache, useful for graceful shutdowns/tests."""

        await asyncio.sleep(0)
        self._seen.clear()
        self._order.clear()
