from __future__ import annotations

import asyncio

from emotion_diary.event_bus import EventBus


def test_event_bus_publish_subscribe():
    async def _run():
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.payload["value"])

        bus.subscribe("test.event", handler)
        await bus.publish("test.event", {"value": 42})
        assert received == [42]

    asyncio.run(_run())
