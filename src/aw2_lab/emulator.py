"""Process lifecycle for the mGBA emulator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EmulatorMode(StrEnum):
    """Supported mGBA frontend modes."""

    HEADLESS = "headless"
    WINDOWED = "windowed"


@dataclass(frozen=True, slots=True)
class EmulatorSettings:
    """ROM and frontend configuration shared by the API and launcher."""

    rom_path: Path
    mode: EmulatorMode = EmulatorMode.HEADLESS
    headless_executable: str | None = None
    windowed_executable: str | None = None


class EmulatorLaunchError(RuntimeError):
    """Raised when mGBA cannot be started or exits during startup."""


class EmulatorLauncher:
    """Start and stop one mGBA process for the lifetime of the API server."""

    def __init__(self, settings: EmulatorSettings) -> None:
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the managed emulator process is still alive."""
        return self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        """Launch mGBA with the configured ROM and frontend."""
        executable = (
            self.settings.headless_executable or "mgba"
            if self.settings.mode is EmulatorMode.HEADLESS
            else self.settings.windowed_executable or "mgba-qt"
        )
        try:
            process = await asyncio.create_subprocess_exec(executable, str(self.settings.rom_path))
        except OSError as error:
            raise EmulatorLaunchError(
                f"Could not start mGBA executable {executable!r}: {error}"
            ) from error
        self.process = process

        await asyncio.sleep(0)
        if process.returncode is not None:
            return_code = process.returncode
            self.process = None
            raise EmulatorLaunchError(
                f"mGBA exited during startup with status {return_code} (executable {executable!r})"
            )

    async def stop(self) -> None:
        """Terminate mGBA, escalating to kill if it does not exit promptly."""
        process = self.process
        self.process = None
        if process is None or process.returncode is not None:
            return

        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
