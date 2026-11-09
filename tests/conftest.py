"""Test-only adapters for environments without working asyncio worker dispatch."""

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolate_application_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep default application storage from reading or writing user data."""
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    elif sys.platform == "darwin":
        monkeypatch.setenv("HOME", str(tmp_path))
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))


@pytest.fixture(autouse=True)
def inline_worker_calls(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Run awaited local work inline; keep opt-in emulator pipe tests concurrent."""
    if request.path.name == "test_frame_gate_integration.py":
        return

    async def run_asyncio_inline(function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    async def run_anyio_inline(function: Callable[..., Any], /, *args: Any, **_kwargs: Any) -> Any:
        return function(*args)

    # Thread-pool scheduling stalls in the packaged pytest environment. Unit tests
    # check the filesystem and route behavior, not worker scheduling itself.
    monkeypatch.setattr(asyncio, "to_thread", run_asyncio_inline)
    monkeypatch.setattr("anyio.to_thread.run_sync", run_anyio_inline)
