"""Notifier agent prepares responses for Telegram delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from emotion_diary.event_bus import Event, EventBus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Notifier:
    """Builds Telegram responses from domain events."""

    bus: EventBus

    def __post_init__(self) -> None:
        """Subscribe to events that require user-facing notifications."""
        self.bus.subscribe(
            (
                "checkin.saved",
                "pet.rendered",
                "ping.request",
                "export.ready",
                "delete.done",
            ),
            self.handle,
        )

    async def handle(self, event: Event) -> None:
        """Compose Telegram responses and emit them to the bus.

        Args:
            event: Event containing data to be delivered to a Telegram chat.

        """
        payload = event.payload
        chat_id = payload.get("chat_id")
        if chat_id is None:
            logger.debug("Notifier received payload without chat_id: %s", payload)
            return
        message, extras = self._build_message(event.name, payload)
        if message is None and not extras:
            return
        response = {
            "chat_id": chat_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if message is not None:
            response["text"] = message
        response.update(extras)
        if response.get("text") is None:
            response.pop("text", None)
        if event.name == "pet.rendered":
            response["sprite"] = payload.get("sprite")
        await self.bus.publish("tg.response", response)

    def _build_message(
        self, event_name: str, payload: dict
    ) -> tuple[str | None, dict[str, Any]]:
        """Derive message text and extras for a Telegram response.

        Args:
            event_name: Name of the domain event being processed.
            payload: Event payload with contextual data.

        Returns:
            A tuple of optional text and additional Telegram API parameters.

        """
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
            tg_hint = dict(payload.get("tg") or {})
            document_path = tg_hint.get("document_path") or payload.get("file_path")
            caption = "Готов экспорт данных. Файл во вложении."
            if document_path:
                path = Path(document_path)
                if path.exists() and path.is_file():
                    extras["method"] = tg_hint.get("method", "sendDocument")
                    extras["caption"] = caption
                    extras["files"] = {
                        "document": (
                            path.name,
                            path.read_bytes(),
                            "text/csv",
                        )
                    }
                    return None, extras
                return (
                    f"Готов экспорт данных: {document_path}",
                    extras,
                )
            return ("Экспорт не удался: файл не найден.", extras)
        if event_name == "delete.done":
            return "Все данные удалены. Надеемся увидеть вас снова!", extras
        return None, extras
