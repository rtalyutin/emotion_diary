"""Dataclasses describing storage models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(slots=True)
class Ident:
    """Represents a chat-to-user binding."""

    pid: str
    chat_id: int
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert the dataclass to a serialisable dictionary."""
        return {"pid": self.pid, "chat_id": self.chat_id, "created_at": self.created_at}


@dataclass(slots=True)
class User:
    """User notification settings stored in the database."""

    pid: str
    tz: str
    notify_hour: int
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert the dataclass to a serialisable dictionary."""
        return {
            "pid": self.pid,
            "tz": self.tz,
            "notify_hour": self.notify_hour,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class Entry:
    """Mood journal entry persisted for a user."""

    id: Optional[int]
    pid: str
    ts: datetime
    mood: int
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the dataclass to a serialisable dictionary."""
        return {
            "id": self.id,
            "pid": self.pid,
            "ts": self.ts,
            "mood": self.mood,
            "note": self.note,
        }
