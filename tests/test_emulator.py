import asyncio
from pathlib import Path

import pytest

from aw2_lab.emulator import (
    EmulatorLauncher,
    EmulatorLaunchError,
    EmulatorMode,
    EmulatorSettings,
)


class FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode or 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "executable_override", "expected_executable"),
    [
        (EmulatorMode.HEADLESS, None, "mgba-headless"),
        (EmulatorMode.WINDOWED, None, "mgba-qt"),
        (EmulatorMode.HEADLESS, "mgba-test", "mgba-test"),
        (EmulatorMode.WINDOWED, "mgba-qt-test", "mgba-qt-test"),
    ],
)
async def test_launcher_uses_mode_executable_and_stops_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: EmulatorMode,
    executable_override: str | None,
    expected_executable: str,
) -> None:
    rom = tmp_path / "aw2.gba"
    bridge = tmp_path / "bridge.lua"
    bridge.touch()
    calls: list[str] = []
    environment: dict[str, str] = {}
    process = FakeProcess()

    async def create_process(*args: str, env: dict[str, str]) -> FakeProcess:
        calls.extend(args)
        environment.update(env)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=rom,
            mode=mode,
            headless_executable=executable_override,
            windowed_executable=executable_override,
            bridge_script=bridge,
        )
    )

    await launcher.start()

    assert calls == [expected_executable, "--script", str(bridge), str(rom)]
    assert environment["AW2_MGBA_SCRIPTING_CONSOLE"] == "0"
    assert launcher.is_running
    await launcher.stop()
    assert process.terminated
    assert not launcher.is_running


@pytest.mark.anyio
async def test_launcher_enables_scripting_console_when_requested_in_windowed_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bridge = tmp_path / "bridge.lua"
    bridge.touch()
    environment: dict[str, str] = {}

    async def create_process(*args: str, env: dict[str, str]) -> FakeProcess:
        environment.update(env)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=tmp_path / "aw2.gba",
            mode=EmulatorMode.WINDOWED,
            bridge_script=bridge,
            show_scripting_console=True,
        )
    )

    await launcher.start()

    assert environment["AW2_MGBA_SCRIPTING_CONSOLE"] == "1"


@pytest.mark.anyio
async def test_launcher_reports_executable_start_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def create_process(*args: str, **kwargs: object) -> FakeProcess:
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=tmp_path / "aw2.gba",
            mode=EmulatorMode.HEADLESS,
            headless_executable="missing",
        )
    )

    with pytest.raises(EmulatorLaunchError, match="Could not start mGBA"):
        await launcher.start()


@pytest.mark.anyio
async def test_launcher_reports_immediate_process_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def create_process(*args: str, **kwargs: object) -> FakeProcess:
        return FakeProcess(returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(rom_path=tmp_path / "aw2.gba", mode=EmulatorMode.HEADLESS)
    )

    with pytest.raises(EmulatorLaunchError, match="exited during startup"):
        await launcher.start()
