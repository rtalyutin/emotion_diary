"""Deduplication agent filters repeated Telegram updates."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from emotion_diary.event_bus import Event, EventBus


@dataclass(slots=True)
class Dedup:
    """Filters out repeated Telegram updates within a time window."""

    bus: EventBus
    window: timedelta = timedelta(minutes=10)
    _seen: dict[int, datetime] = field(init=False, default_factory=dict)
    _order: deque[tuple[int, datetime]] = field(init=False, default_factory=deque)

    def __post_init__(self) -> None:
        """Subscribe to raw Telegram updates for deduplication."""
        self.bus.subscribe("tg.update", self.handle_update)

    def _prune(self, now: datetime) -> None:
        """Drop cached updates that fall outside the deduplication window.

        Args:
            now: Reference timestamp used to evaluate staleness.

        """
        while self._order and now - self._order[0][1] > self.window:
            update_id, _ = self._order.popleft()
            self._seen.pop(update_id, None)

    async def handle_update(self, event: Event) -> None:
        """Relay unique updates and suppress duplicates.

        Args:
            event: Telegram update event subject to deduplication.

        """
        if event.metadata.get("dedup_passed"):  # pragma: no branch - guard
            return
        update_id = event.payload.get("update_id")
        if update_id is None:  # pragma: no branch - guard
            await self.bus.publish(
                event.name,
                payload=event.payload,
                metadata={**event.metadata, "dedup_passed": True},
            )
            return
        timestamp = event.payload.get("ts")
        if not isinstance(timestamp, datetime):  # pragma: no branch - guard
            timestamp = datetime.now(UTC)
        existing = self._seen.get(update_id)
        if existing and timestamp - existing <= self.window:  # pragma: no branch
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
        """Clear cached update IDs for shutdowns or tests."""
        await asyncio.sleep(0)
        self._seen.clear()
        self._order.clear()
