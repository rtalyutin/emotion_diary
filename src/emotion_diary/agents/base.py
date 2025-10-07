"""Common base utilities for agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from emotion_diary.event_bus import EventBus


class SupportsSubscribe(Protocol):
    """Protocol describing the minimal event bus subscription interface."""

    def subscribe(self, event_name: str | tuple[str, ...], handler):
        """Register a handler for the given event name or tuple of names."""


@dataclass(slots=True)
class Agent:
    """Base class for event-driven agents bound to an :class:`EventBus`."""

    bus: EventBus

    def register(self) -> None:  # pragma: no cover - to be implemented in subclasses
        """Subscribe required handlers on the event bus."""
        raise NotImplementedError
