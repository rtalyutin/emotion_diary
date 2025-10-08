"""Pytest configuration that ensures the project package is importable."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers used across the test suite."""

    config.addinivalue_line(
        "markers", "asyncio: run test coroutine inside a dedicated event loop"
    )


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Execute ``@pytest.mark.asyncio`` tests using ``asyncio`` event loops."""

    marker = pyfuncitem.get_closest_marker("asyncio")
    if marker is None:
        return None

    func = pyfuncitem.obj
    if not asyncio.iscoroutinefunction(func):
        return None

    loop = asyncio.new_event_loop()
    try:
        signature = inspect.signature(func)
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in signature.parameters
            if name in pyfuncitem.funcargs
        }
        loop.run_until_complete(func(**kwargs))
    finally:
        loop.close()

    return True
