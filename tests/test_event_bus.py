"""Tests for the in-process event bus implementation."""

from __future__ import annotations

import asyncio

from emotion_diary.event_bus import Event, EventBus


def test_event_bus_publish_subscribe() -> None:
    """Ensure that events published on the bus reach subscribed handlers."""

    async def _run() -> None:
        """Run the async test scenario for the event bus."""
        bus = EventBus()
        received: list[int] = []

        async def handler(event: Event) -> None:
            """Capture published events for later assertions."""
            received.append(event.payload["value"])

        bus.subscribe("test.event", handler)
        await bus.publish("test.event", {"value": 42})
        assert received == [42]

    asyncio.run(_run())
