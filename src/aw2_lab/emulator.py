"""Process lifecycle for the mGBA emulator."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aw2_lab.bridge import BridgeError, LuaBridgeClient


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
    bridge_ready_timeout: float = 15.0


class EmulatorLaunchError(RuntimeError):
    """Raised when mGBA cannot be started or exits during startup."""


_REQUIRED_BRIDGE_CAPABILITIES = frozenset(
    {
        "connect",
        "set_keys",
        "press_keys",
        "advance_frames",
        "read_memory",
        "read_memory_batch",
        "screenshot",
        "reset",
        "save_state",
        "load_state",
        "save_state_buffer",
        "load_state_buffer",
    }
)


class EmulatorLauncher:
    """Start and stop one mGBA process for the lifetime of the API server."""

    def __init__(self, settings: EmulatorSettings) -> None:
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.bridge: LuaBridgeClient | None = None
        self.build_identity: str | None = None

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
        resolved_executable = shutil.which(executable) or executable
        self.build_identity = await asyncio.to_thread(_build_identity, Path(resolved_executable))
        script = self.settings.bridge_script
        if script is None:
            script = Path(__file__).resolve().parent / "lua" / "bridge.lua"
            if not script.is_file():
                script = Path(__file__).resolve().parents[2] / "lua" / "bridge.lua"
        if not script.is_file():
            raise EmulatorLaunchError(f"Lua bridge script does not exist: {script}")
        environment = os.environ.copy()
        environment["AW2_MGBA_FRAME_GATE"] = "1"
        show_console = (
            self.settings.mode is EmulatorMode.WINDOWED and self.settings.show_scripting_console
        )
        environment["AW2_MGBA_SCRIPTING_CONSOLE"] = "1" if show_console else "0"
        environment["AW2_MGBA_SUPPRESS_TEMP_ROM_WARNING"] = (
            "1" if self.settings.mode is EmulatorMode.WINDOWED else "0"
        )
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
        bridge = LuaBridgeClient(timeout=1.0)
        self.bridge = bridge
        deadline = asyncio.get_running_loop().time() + self.settings.bridge_ready_timeout
        last_error = "no response"
        while True:
            if process.returncode is not None:
                return_code = process.returncode
                self.process = None
                self.bridge = None
                if self.settings.mode is EmulatorMode.WINDOWED:
                    startup_hint = (
                        "check that this build supports Lua scripting and --script, and that a "
                        "display server is available (DISPLAY or WAYLAND_DISPLAY)"
                    )
                else:
                    startup_hint = (
                        "check that this build supports Lua scripting, the --script option, and "
                        "the headless frontend"
                    )
                raise EmulatorLaunchError(
                    f"mGBA exited during startup with status {return_code} "
                    f"(executable {executable!r}); {startup_hint}"
                )
            try:
                handshake = await bridge.connect()
                if handshake.get("protocol_version") != 1 or not isinstance(
                    handshake.get("capabilities"), list
                ):
                    raise BridgeError("Lua bridge returned an unsupported handshake")
                capabilities = handshake["capabilities"]
                if not all(isinstance(capability, str) for capability in capabilities):
                    raise BridgeError("Lua bridge returned an invalid capability list")
                missing_capabilities = sorted(_REQUIRED_BRIDGE_CAPABILITIES - set(capabilities))
                if missing_capabilities:
                    await self.stop()
                    raise EmulatorLaunchError(
                        "Lua bridge is missing required capabilities: "
                        f"{', '.join(missing_capabilities)}; use a bridge script compatible "
                        "with this aw2-lab version"
                    )
                return
            except BridgeError as error:
                last_error = str(error)
            if asyncio.get_running_loop().time() >= deadline:
                await self.stop()
                raise EmulatorLaunchError(
                    f"Lua bridge did not become ready within "
                    f"{self.settings.bridge_ready_timeout:g} seconds "
                    f"(executable {executable!r}, last error: {last_error}); "
                    "check that the selected mGBA frontend supports Lua scripting and that "
                    "bridge port 43128 is available"
                )
            await asyncio.sleep(0.05)

    async def stop(self) -> None:
        """Terminate mGBA, escalating to kill if it does not exit promptly."""
        process = self.process
        self.process = None
        self.bridge = None
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


def _build_identity(executable: Path) -> str:
    resolved = executable.resolve()
    if not resolved.is_file():
        return f"path:{resolved}"
    try:
        with resolved.open("rb") as binary:
            digest = hashlib.file_digest(binary, "sha256").hexdigest()
    except OSError:
        return f"path:{resolved}"
    return f"sha256:{digest}"
