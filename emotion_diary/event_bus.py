"""Asynchronous in-memory event bus used by the agents."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, MutableMapping, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Event:
    """Domain event with payload and metadata."""

    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def copy(self, *, name: Optional[str] = None, payload: Optional[MutableMapping[str, Any]] = None,
             metadata: Optional[MutableMapping[str, Any]] = None) -> "Event":
        return Event(
            name=name or self.name,
            payload=dict(self.payload if payload is None else payload),
            metadata=dict(self.metadata if metadata is None else metadata),
        )


EventHandler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """Simple pub/sub event bus with asyncio support."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(self, event_name: str | Iterable[str], handler: EventHandler) -> None:
        """Register ``handler`` for the given ``event_name`` or list of names."""

        if isinstance(event_name, str):
            event_names = [event_name]
        else:
            event_names = list(event_name)
        if not event_names:
            raise ValueError("event_name must not be empty")
        for name in event_names:
            logger.debug("Subscribing %s to event %s", getattr(handler, "__qualname__", repr(handler)), name)
            self._subscribers[name].append(handler)

    async def publish(
        self, event_name: str, payload: Optional[MutableMapping[str, Any]] = None,
        metadata: Optional[MutableMapping[str, Any]] = None,
    ) -> None:
        """Publish an event to all registered subscribers."""

        event = Event(name=event_name, payload=dict(payload or {}), metadata=dict(metadata or {}))
        async with self._lock:
            subscribers = list(self._subscribers.get(event_name, ())) + list(self._subscribers.get("*", ()))
        if not subscribers:
            logger.debug("No subscribers for event %s", event_name)
            return

        awaitables: List[Awaitable[None]] = []
        for handler in subscribers:
            try:
                result = handler(event)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Unhandled exception in event handler %s", handler)
                continue
            if inspect.isawaitable(result):
                awaitables.append(asyncio.ensure_future(result))
        if awaitables:
            await asyncio.gather(*awaitables, return_exceptions=True)

    def clear(self) -> None:
        """Remove all subscribers (useful for tests)."""

        self._subscribers.clear()
