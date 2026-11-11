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


def sharkport_save(rom_identity: bytes, payload: bytes) -> bytes:
    def field(value: bytes) -> bytes:
        return len(value).to_bytes(4, "little") + value

    header = rom_identity + bytes(0x1C - len(rom_identity))
    record = header + payload
    return b"".join(
        (
            len(b"SharkPortSave").to_bytes(4, "little"),
            b"SharkPortSave",
            (0x000F0000).to_bytes(4, "little"),
            field(b"Advance Wars 2"),
            field(b"2002-01-01"),
            field(b"all unlocks"),
            len(record).to_bytes(4, "little"),
            record,
            bytes(4),
        )
    )


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


@pytest.mark.anyio
async def test_server_isolates_rom_and_save_copy_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", bridge_ready)
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(b"test rom")
    save = rom.with_suffix(".sav")
    save.write_bytes(b"original save")
    script = tmp_path / "bridge.lua"
    script.touch()
    copied = []

    async def create_process(*args, **kwargs):
        local = Path(args[-1])
        copied.append(local)
        assert local != rom and local.read_bytes() == rom.read_bytes()
        assert local.with_suffix(".sav").read_bytes() == b"original save"
        bootstrap = Path(args[2])
        assert bootstrap.parent == local.parent
        script_text = bootstrap.read_text()
        assert "emu:loadSaveFile" in script_text
        assert str(local.with_suffix(".sav")) in script_text
        assert str(save) not in script_text
        assert str(script) in script_text
        local.with_suffix(".sav").write_bytes(b"changed isolated save")
        assert (
            str(local.parent)
            in (Path(kwargs["env"]["XDG_CONFIG_HOME"]) / "mgba" / "config.ini").read_text()
        )
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(rom_path=rom, bridge_script=script), isolate_saves=True
    )
    await launcher.start()
    await launcher.stop()
    assert save.read_bytes() == b"original save"
    assert not copied[0].parent.exists()


@pytest.mark.anyio
async def test_launcher_converts_sps_into_temporary_save_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("aw2_lab.emulator.LuaBridgeClient.connect", bridge_ready)
    rom_identity = b"ADVANCEWARS2AW2E"
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(bytes(0xA0) + rom_identity + bytes(0x100))
    adjacent_save = rom.with_suffix(".sav")
    adjacent_save.write_bytes(b"user's existing save")
    payload = bytes(index % 251 for index in range(0x10000))
    profile = tmp_path / "all-unlocked.sps"
    profile.write_bytes(sharkport_save(rom_identity, payload))
    original_profile = profile.read_bytes()
    script = tmp_path / "bridge.lua"
    script.touch()
    copied: dict[str, object] = {}

    async def create_process(*args, **kwargs):
        local_rom = Path(args[-1])
        local_save = local_rom.with_suffix(".sav")
        bootstrap = Path(args[2])
        copied.update(
            rom=local_rom,
            save=local_save,
            bootstrap=bootstrap,
            save_bytes=local_save.read_bytes(),
            script=bootstrap.read_text(),
        )
        assert local_rom != rom
        assert local_save.read_bytes() == payload
        assert str(profile) not in bootstrap.read_text()
        assert str(local_save) in bootstrap.read_text()
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    launcher = EmulatorLauncher(
        EmulatorSettings(rom_path=rom, save_profile_path=profile, bridge_script=script)
    )

    await launcher.start()
    await launcher.stop()

    assert profile.read_bytes() == original_profile
    assert adjacent_save.read_bytes() == b"user's existing save"
    assert not Path(copied["rom"].parent).exists()


@pytest.mark.anyio
async def test_launcher_rejects_sps_for_different_rom_without_launching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(bytes(0xA0) + b"ADVANCEWARS2AW2E" + bytes(0x100))
    profile = tmp_path / "other-game.sps"
    profile.write_bytes(sharkport_save(b"OTHER-GAME-ROM!!", bytes(0x10000)))

    async def should_not_launch(*args, **kwargs):
        raise AssertionError("mGBA should not start with a mismatched save profile")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", should_not_launch)
    launcher = EmulatorLauncher(EmulatorSettings(rom_path=rom, save_profile_path=profile))

    with pytest.raises(EmulatorLaunchError, match="belongs to a different ROM"):
        await launcher.start()
