"""Agent that picks a virtual pet sprite for the notification."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from emotion_diary.event_bus import Event, EventBus

SPRITES = {
    -1: ["sprite_sad_1.png", "sprite_sad_2.png"],
    0: ["sprite_neutral_1.png", "sprite_neutral_2.png"],
    1: ["sprite_happy_1.png", "sprite_happy_2.png"],
}


@dataclass(slots=True)
class PetRender:
    """Chooses pet sprites based on mood events."""

    bus: EventBus
    assets_dir: Path | None = None

    def __post_init__(self) -> None:
        """Subscribe to events that require sprite rendering."""
        self.bus.subscribe(("checkin.saved", "ping.request"), self.handle)

    async def handle(self, event: Event) -> None:
        """Pick a sprite for the provided event and emit the result.

        Args:
            event: Event carrying mood information for sprite selection.

        """
        payload = event.payload
        pid = payload.get("pid")
        chat_id = payload.get("chat_id")
        if pid is None or chat_id is None:
            return
        mood = (
            payload.get("entry", {}).get("mood")
            if "entry" in payload
            else payload.get("mood", 0)
        )
        sprite = self._choose_sprite(int(mood or 0))
        meta = {
            "pid": pid,
            "chat_id": chat_id,
            "sprite": sprite,
            "rendered_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.bus.publish("pet.rendered", meta)

    def _choose_sprite(self, mood: int) -> str:
        """Select a sprite from the assets bundle based on mood.

        Args:
            mood: Mood value used to pick the sprite group.

        Returns:
            Path or filename of the selected sprite image.

        """
        options = SPRITES.get(mood, SPRITES[0])
        sprite = random.choice(options)
        if self.assets_dir:
            return str((self.assets_dir / sprite).resolve())
        return sprite
