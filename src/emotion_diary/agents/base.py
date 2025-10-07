"""Common base utilities for agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from emotion_diary.event_bus import EventBus


class SupportsSubscribe(Protocol):
    def subscribe(self, event_name: str | tuple[str, ...], handler):
        ...


@dataclass(slots=True)
class Agent:
    bus: EventBus

    def register(self) -> None:  # pragma: no cover - to be implemented in subclasses
        raise NotImplementedError
