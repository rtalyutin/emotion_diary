"""High level storage API that uses the database adapters."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import List, Optional

from .adapters import DatabaseAdapter
from .models import Entry, Ident, User

DEFAULT_SALT = "emotion-diary-dev"


@dataclass(slots=True)
class Storage:
    adapter: DatabaseAdapter
    ident_salt: str | None = None

    def __post_init__(self) -> None:
        self.ident_salt = self.ident_salt or os.getenv("EMOTION_DIARY_IDENT_SALT", DEFAULT_SALT)
        self.adapter.ensure_schema()

    # Ident operations -------------------------------------------------
    def get_or_create_ident(self, chat_id: int) -> Ident:
        row = self.adapter.fetchone("SELECT pid, chat_id, created_at FROM ident WHERE chat_id=?", (chat_id,))
        if row:
            created_at = row["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            return Ident(pid=row["pid"], chat_id=row["chat_id"], created_at=created_at)
        pid = self._hash_chat_id(chat_id)
        created_at = datetime.now(timezone.utc)
        self.adapter.execute(
            "INSERT INTO ident (pid, chat_id, created_at) VALUES (?, ?, ?)",
            (pid, chat_id, created_at),
        )
        self.ensure_user_record(pid)
        return Ident(pid=pid, chat_id=chat_id, created_at=created_at)

    def ensure_user_record(self, pid: str, tz: str = "UTC", notify_hour: int = 20) -> User:
        row = self.adapter.fetchone("SELECT pid, tz, notify_hour, created_at FROM users WHERE pid=?", (pid,))
        if row:
            created_at = row["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            if row["notify_hour"] != notify_hour or row["tz"] != tz:
                self.adapter.execute(
                    "UPDATE users SET tz=?, notify_hour=? WHERE pid=?",
                    (tz, notify_hour, pid),
                )
                return User(pid=pid, tz=tz, notify_hour=notify_hour, created_at=created_at)
            return User(pid=row["pid"], tz=row["tz"], notify_hour=row["notify_hour"], created_at=created_at)
        created_at = datetime.now(timezone.utc)
        self.adapter.execute(
            "INSERT INTO users (pid, tz, notify_hour, created_at) VALUES (?, ?, ?, ?)",
            (pid, tz, notify_hour, created_at),
        )
        return User(pid=pid, tz=tz, notify_hour=notify_hour, created_at=created_at)

    # Entry operations -------------------------------------------------
    def save_entry(self, pid: str, ts: datetime, mood: int, note: Optional[str]) -> Entry:
        cur = self.adapter.execute(
            "INSERT INTO entries (pid, ts, mood, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, ts, mood, note, datetime.now(timezone.utc)),
        )
        entry_id = getattr(cur, "lastrowid", None)
        return Entry(id=entry_id, pid=pid, ts=ts, mood=mood, note=note)

    def list_entries(self, pid: str) -> List[Entry]:
        rows = self.adapter.fetchall(
            "SELECT id, pid, ts, mood, note FROM entries WHERE pid=? ORDER BY ts",
            (pid,),
        )
        entries: List[Entry] = []
        for row in rows:
            ts = row["ts"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            entries.append(Entry(id=row["id"], pid=row["pid"], ts=ts, mood=row["mood"], note=row["note"]))
        return entries

    def delete_user(self, pid: str) -> None:
        self.adapter.execute("DELETE FROM entries WHERE pid=?", (pid,))
        self.adapter.execute("DELETE FROM users WHERE pid=?", (pid,))
        self.adapter.execute("DELETE FROM ident WHERE pid=?", (pid,))

    # Scheduler helpers ------------------------------------------------
    def due_users(self, hour: int) -> List[tuple[str, int]]:
        rows = self.adapter.fetchall(
            """
            SELECT users.pid as pid, ident.chat_id as chat_id
            FROM users
            JOIN ident ON ident.pid = users.pid
            WHERE users.notify_hour=?
            """,
            (hour,),
        )
        return [(row["pid"], row["chat_id"]) for row in rows]

    # Internal ---------------------------------------------------------
    def _hash_chat_id(self, chat_id: int) -> str:
        salt = self.ident_salt or DEFAULT_SALT
        return hmac.new(salt.encode(), str(chat_id).encode(), sha256).hexdigest()


__all__ = ["Storage", "Entry", "Ident", "User"]
