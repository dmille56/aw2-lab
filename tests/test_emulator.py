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
    ("mode", "expected_executable"),
    [(EmulatorMode.HEADLESS, "mgba-test"), (EmulatorMode.WINDOWED, "mgba-qt-test")],
)
async def test_launcher_uses_mode_executable_and_stops_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: EmulatorMode,
    expected_executable: str,
) -> None:
    rom = tmp_path / "aw2.gba"
    calls: list[str] = []
    process = FakeProcess()

    async def create_process(*args: str) -> FakeProcess:
        calls.extend(args)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=rom,
            mode=mode,
            headless_executable="mgba-test",
            windowed_executable="mgba-qt-test",
        )
    )

    await launcher.start()

    assert calls == [expected_executable, str(rom)]
    assert launcher.is_running
    await launcher.stop()
    assert process.terminated
    assert not launcher.is_running


@pytest.mark.anyio
async def test_launcher_reports_executable_start_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def create_process(*args: str) -> FakeProcess:
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
    async def create_process(*args: str) -> FakeProcess:
        return FakeProcess(returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(rom_path=tmp_path / "aw2.gba", mode=EmulatorMode.HEADLESS)
    )

    with pytest.raises(EmulatorLaunchError, match="exited during startup"):
        await launcher.start()
