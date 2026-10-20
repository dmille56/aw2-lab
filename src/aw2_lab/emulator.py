"""Process lifecycle for the mGBA emulator."""

from __future__ import annotations

import asyncio
import os
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
    bridge_script: Path | None = None
    show_scripting_console: bool = False


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
            self.settings.headless_executable or "mgba-headless"
            if self.settings.mode is EmulatorMode.HEADLESS
            else self.settings.windowed_executable or "mgba-qt"
        )
        script = self.settings.bridge_script
        if script is None:
            script = Path(__file__).resolve().parent / "lua" / "bridge.lua"
            if not script.is_file():
                script = Path(__file__).resolve().parents[2] / "lua" / "bridge.lua"
        if not script.is_file():
            raise EmulatorLaunchError(f"Lua bridge script does not exist: {script}")
        environment = os.environ.copy()
        show_console = (
            self.settings.mode is EmulatorMode.WINDOWED and self.settings.show_scripting_console
        )
        environment["AW2_MGBA_SCRIPTING_CONSOLE"] = "1" if show_console else "0"
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "--script",
                str(script),
                str(self.settings.rom_path),
                env=environment,
            )
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
                f"mGBA exited during startup with status {return_code} (executable {executable!r}); "
                "check that this mGBA build supports Lua scripting and the --script option"
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
