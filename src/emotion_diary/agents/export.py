"""Agent responsible for producing CSV exports of mood entries."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from emotion_diary.event_bus import Event, EventBus
from emotion_diary.storage import Entry, Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Export:
    """Creates CSV exports and announces their availability."""

    bus: EventBus
    storage: Storage
    export_dir: Path

    def __post_init__(self) -> None:
        """Prepare filesystem storage and subscribe to export requests."""
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.bus.subscribe("export.request", self.handle)

    async def handle(self, event: Event) -> None:
        """Generate CSV export for a user upon request.

        Args:
            event: Event with identifiers describing the export context.

        """
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
        """Fetch entries for export using storage APIs or fallbacks.

        Args:
            pid: Persistent identifier of the user requesting export.

        Returns:
            The list of entries sorted by timestamp for the export file.

        """
        try:
            return list(self.storage.list_entries(pid))
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "Failed to load entries via storage.list_entries for %s: %s", pid, exc
            )
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
        """Materialise a CSV file with the provided entries.

        Args:
            pid: Persistent identifier used to name the export file.
            entries: Iterable of storage entries to serialise.

        Returns:
            Absolute path to the generated CSV file.

        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        file_path = self.export_dir / f"{pid}-{timestamp}.csv"
        with file_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["ts", "mood", "note"])
            for entry in entries:
                writer.writerow([entry.ts.isoformat(), entry.mood, entry.note or ""])
        return file_path
