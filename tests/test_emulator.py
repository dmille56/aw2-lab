import asyncio
from pathlib import Path

import pytest

from aw2_lab.emulator import (
    EmulatorLauncher,
    EmulatorLaunchError,
    EmulatorMode,
    EmulatorSettings,
)


async def bridge_ready(_self: object) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "capabilities": [
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
        ],
    }


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
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", bridge_ready)
    rom = tmp_path / "aw2.gba"
    bridge = tmp_path / "bridge.lua"
    bridge.touch()
    calls: list[str] = []
    environment: dict[str, str] = {}
    output_settings: dict[str, int | None] = {}
    process = FakeProcess()

    async def create_process(
        *args: str,
        env: dict[str, str],
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> FakeProcess:
        calls.extend(args)
        environment.update(env)
        output_settings.update(stdout=stdout, stderr=stderr)
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
    assert environment["AW2_MGBA_FRAME_GATE"] == "1"
    assert environment["AW2_MGBA_SUPPRESS_TEMP_ROM_WARNING"] == (
        "1" if mode is EmulatorMode.WINDOWED else "0"
    )
    assert output_settings == {"stdout": None, "stderr": None}
    assert launcher.is_running
    await launcher.stop()
    assert process.terminated
    assert not launcher.is_running


@pytest.mark.anyio
async def test_launcher_enables_scripting_console_when_requested_in_windowed_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", bridge_ready)
    bridge = tmp_path / "bridge.lua"
    bridge.touch()
    environment: dict[str, str] = {}

    async def create_process(
        *args: str,
        env: dict[str, str],
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> FakeProcess:
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
async def test_launcher_can_suppress_emulator_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", bridge_ready)
    bridge = tmp_path / "bridge.lua"
    bridge.touch()
    output_settings: dict[str, int | None] = {}

    async def create_process(
        *args: str,
        env: dict[str, str],
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> FakeProcess:
        output_settings.update(stdout=stdout, stderr=stderr)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=tmp_path / "aw2.gba",
            bridge_script=bridge,
            suppress_emulator_output=True,
        )
    )

    await launcher.start()

    assert output_settings == {
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
    }


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

    with pytest.raises(
        EmulatorLaunchError, match=r"Could not start mGBA executable 'missing':.*missing"
    ):
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

    with pytest.raises(
        EmulatorLaunchError,
        match=r"mGBA exited during startup with status 1.*supports Lua scripting.*headless frontend",
    ):
        await launcher.start()


@pytest.mark.anyio
async def test_launcher_requires_a_valid_bridge_handshake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bridge_script = tmp_path / "bridge.lua"
    bridge_script.touch()
    process = FakeProcess()

    async def create_process(*args: str, **kwargs: object) -> FakeProcess:
        return process

    async def bridge_unavailable(self: object) -> dict[str, object]:
        from aw2_lab.bridge import BridgeError

        raise BridgeError("connection refused")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", bridge_unavailable)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=tmp_path / "aw2.gba",
            bridge_script=bridge_script,
            bridge_ready_timeout=0,
        )
    )

    with pytest.raises(
        EmulatorLaunchError,
        match=r"Lua bridge did not become ready.*connection refused.*supports Lua scripting.*port 43128",
    ):
        await launcher.start()
    assert process.terminated
    assert not launcher.is_running


@pytest.mark.anyio
async def test_launcher_rejects_missing_bridge_capabilities(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bridge_script = tmp_path / "bridge.lua"
    bridge_script.touch()
    process = FakeProcess()

    async def create_process(*args: str, **kwargs: object) -> FakeProcess:
        return process

    async def incomplete_handshake(_self: object) -> dict[str, object]:
        return {"protocol_version": 1, "capabilities": ["connect", "advance_frames"]}

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", incomplete_handshake)
    launcher = EmulatorLauncher(
        EmulatorSettings(
            rom_path=tmp_path / "aw2.gba",
            bridge_script=bridge_script,
            bridge_ready_timeout=5,
        )
    )

    with pytest.raises(
        EmulatorLaunchError,
        match=r"missing required capabilities: .*load_state.*compatible with this aw2-lab version",
    ):
        await launcher.start()

    assert process.terminated
    assert not launcher.is_running
