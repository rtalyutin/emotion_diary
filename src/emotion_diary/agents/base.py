"""Common base utilities for agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from emotion_diary.event_bus import EventBus, EventHandler


class SupportsSubscribe(Protocol):
    """Protocol describing the minimal event bus subscription interface."""

    def subscribe(
        self, event_name: str | tuple[str, ...], handler: EventHandler
    ) -> None:
        """Register a handler for the given event name or tuple of names."""


@dataclass(slots=True)
class Agent(ABC):
    """Base class for event-driven agents bound to an :class:`EventBus`."""

    bus: EventBus

    @abstractmethod
    def register(self) -> None:
        """Subscribe required handlers on the event bus."""
        raise NotImplementedError  # pragma: no cover - enforced by abstractmethod
