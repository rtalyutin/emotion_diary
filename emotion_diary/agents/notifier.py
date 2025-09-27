"""Notifier agent prepares responses for Telegram delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from emotion_diary.event_bus import Event, EventBus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Notifier:
    bus: EventBus

    def __post_init__(self) -> None:
        self.bus.subscribe(
            ("checkin.saved", "pet.rendered", "ping.request", "export.ready", "delete.done"),
            self.handle,
        )

    async def handle(self, event: Event) -> None:
        payload = event.payload
        chat_id = payload.get("chat_id")
        if chat_id is None:
            logger.debug("Notifier received payload without chat_id: %s", payload)
            return
        message, extras = self._build_message(event.name, payload)
        if message is None:
            return
        response = {
            "chat_id": chat_id,
            "text": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        response.update(extras)
        if event.name == "pet.rendered":
            response["sprite"] = payload.get("sprite")
        await self.bus.publish("tg.response", response)

    def _build_message(self, event_name: str, payload: dict) -> tuple[str | None, dict[str, Any]]:
        extras: dict[str, Any] = {}
        if event_name == "checkin.saved":
            mood = payload.get("entry", {}).get("mood")
            return f"Записал настроение: {mood}. Спасибо, что поделились!", extras
        if event_name == "pet.rendered":
            sprite = payload.get("sprite")
            return f"Ваш питомец готов: {sprite}", extras
        if event_name == "ping.request":
            extras["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {"text": "🙂/+1", "callback_data": "mood:+1"},
                        {"text": "😐/0", "callback_data": "mood:0"},
                        {"text": "🙁/-1", "callback_data": "mood:-1"},
                    ]
                ]
            }
            return "Пора рассказать о настроении. Как прошёл день?", extras
        if event_name == "export.ready":
            link = payload.get("file_path")
            return f"Готов экспорт данных: {link}", extras
        if event_name == "delete.done":
            return "Все данные удалены. Надеемся увидеть вас снова!", extras
        return None, extras
