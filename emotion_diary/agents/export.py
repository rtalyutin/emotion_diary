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
        entries = self.storage.list_entries(pid)
        file_path = self._write_csv(pid, entries)
        await self.bus.publish(
            "export.ready",
            {
                "pid": pid,
                "chat_id": chat_id,
                "file_path": str(file_path),
            },
        )

    def _write_csv(self, pid: str, entries: Iterable[Entry]) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        file_path = self.export_dir / f"{pid}-{timestamp}.csv"
        with file_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["ts", "mood", "note"])
            for entry in entries:
                writer.writerow([entry.ts.isoformat(), entry.mood, entry.note or ""])
        return file_path
