"""Process lifecycle for the mGBA emulator."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.save_profile import decode_sharkport_save


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
    suppress_emulator_output: bool = False
    bridge_ready_timeout: float = 15.0
    save_profile_path: Path | None = None


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

    def __init__(self, settings: EmulatorSettings, *, isolate_saves: bool = False) -> None:
        self.settings = settings
        self._isolate_saves = isolate_saves
        self._workspace: tempfile.TemporaryDirectory[str] | None = None
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
        rom_path = self.settings.rom_path
        profile_path = self.settings.save_profile_path
        try:
            if profile_path is not None:
                profile_path = profile_path.expanduser().resolve()
                if not profile_path.is_file():
                    raise EmulatorLaunchError(
                        f"Configured save profile is not a file: {profile_path}"
                    )
                if profile_path.suffix.lower() not in {".sav", ".sps"}:
                    raise EmulatorLaunchError(
                        "Configured save profile must be an mGBA .sav or .sps"
                    )

            if self._isolate_saves or profile_path is not None:
                self._workspace = tempfile.TemporaryDirectory(prefix="aw2-runtime-")
                root = Path(self._workspace.name)
                local_rom = root / rom_path.name
                shutil.copyfile(rom_path, local_rom)
                source_save = profile_path or rom_path.with_suffix(".sav")
                if source_save.is_file():
                    local_save = local_rom.with_suffix(".sav")
                    if source_save.suffix.lower() == ".sps":
                        local_save.write_bytes(decode_sharkport_save(source_save, rom_path))
                    else:
                        shutil.copyfile(source_save, local_save)
                    # The headless frontend does not reliably autoload this copy.
                    # Bind the core to the isolated save before exposing the bridge.
                    bootstrap = root / "bootstrap.lua"
                    bootstrap.write_text(
                        f"assert(emu:loadSaveFile({_lua_string(str(local_save))}, false), "
                        "'Cannot load isolated cartridge save')\n"
                        "emu:reset()\n"
                        f"dofile({_lua_string(str(script.resolve()))})\n"
                    )
                    script = bootstrap
                config = root / "config" / "mgba"
                config.mkdir(parents=True)
                (config / "config.ini").write_text(
                    "".join(
                        f"[ports.{frontend}]\nsavegamePath={root}\nsavestatePath={root}\n"
                        for frontend in ("headless", "qt")
                    )
                )
                environment["XDG_CONFIG_HOME"] = str(config.parent)
                environment["XDG_DATA_HOME"] = str(root / "data")
                environment["XDG_CACHE_HOME"] = str(root / "cache")
                rom_path = local_rom
        except EmulatorLaunchError:
            self._cleanup_workspace()
            raise
        except (OSError, ValueError) as error:
            self._cleanup_workspace()
            if profile_path is not None and profile_path.suffix.lower() == ".sps":
                raise EmulatorLaunchError(
                    f"Cannot load configured GameShark save: {error}"
                ) from error
            raise EmulatorLaunchError("Cannot prepare the isolated emulator files") from error
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "--script",
                str(script),
                str(rom_path),
                env=environment,
                stdout=(
                    asyncio.subprocess.DEVNULL if self.settings.suppress_emulator_output else None
                ),
                stderr=(
                    asyncio.subprocess.DEVNULL if self.settings.suppress_emulator_output else None
                ),
            )
        except OSError as error:
            self._cleanup_workspace()
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
                self._cleanup_workspace()
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
            self._cleanup_workspace()
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
        self._cleanup_workspace()

    def _cleanup_workspace(self) -> None:
        if self._workspace is not None:
            self._workspace.cleanup()
            self._workspace = None


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


def _lua_string(value: str) -> str:
    """Quote paths as Lua long strings without interpreting filename contents."""
    separator = ""
    while f"]{separator}]" in value or value.endswith(f"]{separator}"):
        separator += "="
    return f"[{separator}[{value}]{separator}]"
