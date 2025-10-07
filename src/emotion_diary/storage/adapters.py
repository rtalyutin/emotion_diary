"""Database adapters supporting SQLite and PostgreSQL."""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

try:  # pragma: no cover - optional dependency
    import psycopg
except Exception:  # pragma: no cover - fallback when psycopg is unavailable
    psycopg = None  # type: ignore


class DatabaseAdapter(ABC):
    """Minimal DB-API wrapper used by the storage layer."""

    placeholder: str = "?"

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create missing tables and indexes required by the storage layer."""

    @abstractmethod
    @contextmanager
    def cursor(self) -> Iterator[Any]:
        """Return a context-managed cursor that automatically commits or rolls back."""

    def execute(self, query: str, params: Sequence[Any] | None = None) -> Any:
        """Execute a statement returning the raw cursor.

        Args:
            query: SQL query to execute.
            params: Positional parameters to interpolate.

        Returns:
            Cursor returned by the underlying driver.

        """
        with self.cursor() as cur:
            cur.execute(self._normalize_query(query), params or [])
            return cur

    def executemany(self, query: str, params_seq: Iterable[Sequence[Any]]) -> Any:
        """Execute a statement multiple times using a sequence of parameters.

        Args:
            query: SQL query to execute.
            params_seq: Sequence of positional parameter tuples.

        Returns:
            Cursor after executing the statement.

        """
        with self.cursor() as cur:
            cur.executemany(self._normalize_query(query), params_seq)
            return cur

    def fetchone(self, query: str, params: Sequence[Any] | None = None) -> Any:
        """Fetch a single row using the provided query.

        Args:
            query: SQL query to execute.
            params: Positional parameters to interpolate.

        Returns:
            First row returned by the query or ``None``.

        """
        with self.cursor() as cur:
            cur.execute(self._normalize_query(query), params or [])
            return cur.fetchone()

    def fetchall(self, query: str, params: Sequence[Any] | None = None) -> list[Any]:
        """Fetch all rows from the query result as a list.

        Args:
            query: SQL query to execute.
            params: Positional parameters to interpolate.

        Returns:
            List of rows returned by the query.

        """
        with self.cursor() as cur:
            cur.execute(self._normalize_query(query), params or [])
            rows = cur.fetchall()
        return list(rows)

    def _normalize_query(self, query: str) -> str:
        """Return a query string compatible with the underlying driver."""
        return query


class SQLiteAdapter(DatabaseAdapter):
    """SQLite implementation of :class:`DatabaseAdapter`."""

    def __init__(self, dsn: str) -> None:
        """Connect to SQLite and configure database pragmas.

        Args:
            dsn: Database path or special ``:memory:`` name.

        """
        self._connection = sqlite3.connect(dsn, detect_types=sqlite3.PARSE_DECLTYPES)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")

    def ensure_schema(self) -> None:
        """Create tables used by the bot when they are missing."""
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ident (
                    pid TEXT PRIMARY KEY,
                    chat_id INTEGER UNIQUE NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    pid TEXT PRIMARY KEY REFERENCES ident(pid) ON DELETE CASCADE,
                    tz TEXT NOT NULL,
                    notify_hour INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pid TEXT NOT NULL REFERENCES ident(pid) ON DELETE CASCADE,
                    ts TIMESTAMP NOT NULL,
                    mood INTEGER NOT NULL,
                    note TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_pid_ts ON entries(pid, ts)")

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        """Yield a SQLite cursor and commit on success."""
        cur = self._connection.cursor()
        try:
            yield cur
            self._connection.commit()
        finally:
            cur.close()


class PostgresAdapter(DatabaseAdapter):  # pragma: no cover - requires psycopg
    """PostgreSQL implementation of :class:`DatabaseAdapter`."""

    placeholder: str = "%s"

    def __init__(self, dsn: str) -> None:
        """Create a PostgreSQL connection using ``psycopg``.

        Args:
            dsn: PostgreSQL connection string.

        Raises:
            RuntimeError: If ``psycopg`` is not installed.

        """
        if psycopg is None:  # pragma: no cover - runtime guard
            raise RuntimeError("psycopg is required for PostgresAdapter")
        self._dsn = dsn
        self._connection = psycopg.connect(dsn, autocommit=True)

    def ensure_schema(self) -> None:
        """Create tables used by the bot when they are missing."""
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ident (
                    pid TEXT PRIMARY KEY,
                    chat_id BIGINT UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    pid TEXT PRIMARY KEY REFERENCES ident(pid) ON DELETE CASCADE,
                    tz TEXT NOT NULL,
                    notify_hour INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id SERIAL PRIMARY KEY,
                    pid TEXT NOT NULL REFERENCES ident(pid) ON DELETE CASCADE,
                    ts TIMESTAMPTZ NOT NULL,
                    mood INTEGER NOT NULL,
                    note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_pid_ts ON entries(pid, ts)")

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        """Yield a PostgreSQL cursor for executing commands."""
        cur = self._connection.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def _normalize_query(self, query: str) -> str:
        """Convert SQLite-style placeholders into PostgreSQL compatible ones."""
        return query.replace("?", "%s")
