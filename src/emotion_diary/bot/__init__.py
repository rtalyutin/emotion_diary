"""Command line entry point for running Emotion Diary services."""

from __future__ import annotations

# Import the CLI module eagerly so that coverage measures it during tests.
from . import __main__ as cli  # noqa: F401

__all__ = ["cli"]
