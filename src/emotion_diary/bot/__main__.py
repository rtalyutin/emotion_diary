"""Command line entry-point for Emotion Diary bot services."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import UTC
from pathlib import Path

from emotion_diary import __version__
from emotion_diary.agents import (
    CheckinWriter,
    Dedup,
    Delete,
    Export,
    Notifier,
    PetRender,
    Router,
)
from emotion_diary.assets import ensure_builtin_assets
from emotion_diary.event_bus import EventBus
from emotion_diary.storage import (
    DatabaseAdapter,
    PostgresAdapter,
    SQLiteAdapter,
    Storage,
)

from .transport import TelegramAPI, TelegramResponder, run_polling, run_webhook

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = "emotion_diary.db"
DEFAULT_EXPORT_DIR = Path(os.getenv("EMOTION_DIARY_EXPORT_DIR", "./exports"))
BASE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_ASSETS = os.getenv("EMOTION_DIARY_ASSETS_DIR")
DEFAULT_ASSETS_DIR = (
    Path(_DEFAULT_ASSETS).expanduser() if _DEFAULT_ASSETS else (BASE_DIR / "assets")
)


def build_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for bot services."""
    parser = argparse.ArgumentParser(description="Emotion Diary bot entry-point")
    parser.add_argument(
        "--mode", choices=["polling", "webhook", "scheduler"], required=True
    )
    parser.add_argument(
        "--dsn", default=f"sqlite:///{DEFAULT_SQLITE_PATH}", help="Database DSN"
    )
    parser.add_argument(
        "--export-dir", default=str(DEFAULT_EXPORT_DIR), help="Directory for exports"
    )
    parser.add_argument(
        "--assets-dir",
        default=str(DEFAULT_ASSETS_DIR),
        help="Directory that stores sprite assets",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Webhook host")
    parser.add_argument("--port", type=int, default=8080, help="Webhook port")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    parser.add_argument(
        "--scheduler-hour",
        type=int,
        help="Force scheduler hour instead of current UTC hour",
    )
    parser.add_argument(
        "--version", action="version", version=f"emotion-diary {__version__}"
    )
    return parser


def create_storage(dsn: str) -> Storage:
    """Instantiate storage using a DSN string.

    Args:
        dsn: Database connection string supporting SQLite or PostgreSQL.

    Returns:
        Configured :class:`Storage` instance.

    """
    adapter: DatabaseAdapter
    if dsn.startswith("postgres"):
        adapter = PostgresAdapter(dsn)
    elif dsn.startswith("sqlite:///"):
        adapter = SQLiteAdapter(dsn.replace("sqlite:///", "", 1) or ":memory:")
    else:
        adapter = SQLiteAdapter(dsn)
    return Storage(adapter)


def bootstrap(
    bus: EventBus,
    storage: Storage,
    export_dir: Path,
    assets_dir: Path,
    api: TelegramAPI,
) -> None:
    """Wire core agents and responders to the event bus.

    Args:
        bus: Shared event bus instance.
        storage: Storage facade used by agents.
        export_dir: Directory where exports will be generated.
        assets_dir: Directory with sprite assets.
        api: Telegram API client used for outgoing messages.

    """
    Dedup(bus)
    Router(bus, storage)
    CheckinWriter(bus, storage)
    PetRender(bus, assets_dir=assets_dir)
    Notifier(bus)
    Export(bus, storage, export_dir=export_dir)
    Delete(bus, storage)
    TelegramResponder(bus, api)


async def run_scheduler(
    bus: EventBus, storage: Storage, forced_hour: int | None = None
) -> None:
    """Emit reminder events for users scheduled at the current hour.

    Args:
        bus: Event bus used to publish events.
        storage: Storage facade to fetch due users.
        forced_hour: Optional override for the hour in UTC.

    """
    from datetime import datetime

    hour = forced_hour if forced_hour is not None else datetime.now(UTC).hour
    logger.info("Running scheduler for hour %s", hour)
    for pid, chat_id in storage.due_users(hour):
        await bus.publish("ping.request", {"pid": pid, "chat_id": chat_id})
    logger.info("Scheduler finished")


async def async_main(args: argparse.Namespace) -> None:
    """Entry point for asynchronous bot orchestration.

    Args:
        args: Parsed CLI arguments.

    Raises:
        RuntimeError: If mandatory environment variables are missing.

    """
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN environment variable must be set")
    api = TelegramAPI(bot_token)
    bus = EventBus()
    storage = create_storage(args.dsn)
    export_dir = Path(args.export_dir).expanduser().resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(args.assets_dir).expanduser().resolve()
    bundled_assets_dir = (BASE_DIR / "assets").resolve()
    if assets_dir == bundled_assets_dir:
        ensure_builtin_assets(assets_dir)
    elif not assets_dir.exists():
        raise RuntimeError(f"Assets directory does not exist: {assets_dir}")
    bootstrap(bus, storage, export_dir, assets_dir, api)

    if args.mode == "polling":
        await run_polling(bus, api)
    elif args.mode == "webhook":
        secret = os.getenv("WEBHOOK_SECRET")
        if not secret:
            raise RuntimeError(
                "WEBHOOK_SECRET environment variable must be set for webhook mode"
            )
        await run_webhook(args.host, args.port, bus, secret=secret)
    elif args.mode == "scheduler":
        await run_scheduler(bus, storage, forced_hour=args.scheduler_hour)
    else:  # pragma: no cover - argparse ensures mode
        raise ValueError(f"Unsupported mode {args.mode}")


def main() -> None:
    """Parse CLI arguments and run the async entry point."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:  # pragma: no cover - manual interruption
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
