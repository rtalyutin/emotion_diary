"""Agent responsible for CSV exports."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import Entry, Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Export:
    bus: EventBus
    storage: Storage
    export_dir: Path

    def __post_init__(self) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.bus.subscribe("export.request", self.handle)

    async def handle(self, event: Event) -> None:
        payload = event.payload
        pid = payload.get("pid")
        chat_id = payload.get("chat_id")
        if pid is None or chat_id is None:
            logger.debug("Export request missing pid/chat_id: %s", payload)
            return
        entries = self._load_entries(pid)
        file_path = self._write_csv(pid, entries)
        await self.bus.publish(
            "export.ready",
            {
                "pid": pid,
                "chat_id": chat_id,
                "file_path": str(file_path),
                "tg": {
                    "method": "sendDocument",
                    "document_path": str(file_path),
                    "filename": file_path.name,
                },
            },
        )

    def _load_entries(self, pid: str) -> list[Entry]:
        try:
            return list(self.storage.list_entries(pid))
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to load entries via storage.list_entries for %s: %s", pid, exc)
            rows = self.storage.adapter.fetchall(
                "SELECT id, pid, CAST(ts AS TEXT) as ts, mood, note FROM entries WHERE pid=? ORDER BY ts",
                (pid,),
            )
            entries: list[Entry] = []
            for row in rows:
                ts = row["ts"]
                if isinstance(ts, bytes):
                    ts = ts.decode("utf-8")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                entries.append(
                    Entry(
                        id=row["id"],
                        pid=row["pid"],
                        ts=ts,
                        mood=row["mood"],
                        note=row["note"],
                    )
                )
            return entries

    def _write_csv(self, pid: str, entries: Iterable[Entry]) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        file_path = self.export_dir / f"{pid}-{timestamp}.csv"
        with file_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["ts", "mood", "note"])
            for entry in entries:
                writer.writerow([entry.ts.isoformat(), entry.mood, entry.note or ""])
        return file_path
