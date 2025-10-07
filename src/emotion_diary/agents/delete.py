"""Agent that deletes user data on request."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Delete:
    """Handles user data removal requests."""

    bus: EventBus
    storage: Storage

    def __post_init__(self) -> None:
        """Subscribe to delete requests on the event bus."""
        self.bus.subscribe("delete.request", self.handle)

    async def handle(self, event: Event) -> None:
        """Remove user data and acknowledge the deletion.

        Args:
            event: Event describing which user initiated the deletion.

        """
        payload = event.payload
        pid = payload.get("pid")
        chat_id = payload.get("chat_id")
        if pid is None or chat_id is None:
            logger.debug("Delete request missing pid/chat_id: %s", payload)
            return
        self.storage.delete_user(pid)
        await self.bus.publish(
            "delete.done",
            {
                "pid": pid,
                "chat_id": chat_id,
            },
        )
