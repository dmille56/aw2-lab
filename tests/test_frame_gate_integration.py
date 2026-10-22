"""Opt-in checks against a local AW2 ROM and the patched mGBA frontends."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.emulator import (
    EmulatorLauncher,
    EmulatorLaunchError,
    EmulatorMode,
    EmulatorSettings,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_EMULATOR_TESTS") != "1",
    reason="set AW2_RUN_EMULATOR_TESTS=1 and AW2_ROM_PATH to run emulator checks",
)


@pytest.mark.parametrize("mode", list(EmulatorMode))
def test_frame_gate_stays_idle_and_executes_exact_budgets(
    mode: EmulatorMode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    if not rom.is_file():
        pytest.fail("AW2_ROM_PATH must name a local ROM file")
    if mode is EmulatorMode.WINDOWED and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("windowed mode requires a display")
    executable = os.environ.get(
        f"AW2_TEST_MGBA_{mode.name}",
        "mgba-headless" if mode is EmulatorMode.HEADLESS else "mgba-qt",
    )
    if shutil.which(executable) is None:
        pytest.fail(f"mGBA executable is unavailable: {executable}")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 43128)) == 0:
            pytest.fail("bridge port 43128 is occupied; stop the existing emulator first")

    config = tmp_path / "config" / "mgba"
    config.mkdir(parents=True)
    saves = tmp_path / "saves"
    saves.mkdir()
    (config / "config.ini").write_text(
        "".join(
            f"[ports.{frontend}]\nsavegamePath={saves}\nsavestatePath={saves}\n"
            for frontend in ("headless", "qt")
        )
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    if mode is EmulatorMode.HEADLESS:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom.resolve(),
                mode=mode,
                headless_executable=executable,
                windowed_executable=executable,
                bridge_script=Path(__file__).resolve().parents[1] / "lua" / "bridge.lua",
            )
        )
        bridge = LuaBridgeClient(timeout=1)
        await launcher.start()
        try:
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                assert launcher.is_running, "mGBA exited before the bridge became ready"
                try:
                    await bridge.connect()
                    break
                except BridgeError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(0.05)

            frame = await bridge.advance_frames(0)
            assert frame == 0, "the core advanced before receiving its first frame budget"
            for _ in range(3):
                # Wall time is deliberate here: idle must not advance emulation.
                await asyncio.sleep(0.2)
                await bridge.connect()
                await bridge.request("read_memory", address=0x080000AC, length=4)
                assert await bridge.advance_frames(0) == frame
            frame = (frame + 1) % (1 << 32)
            assert await bridge.advance_frames(1) == frame
            initial_batch = await bridge.read_memory_batch([(0x02000000, 16), (0x080000A0, 16)])
            snapshot = await bridge.read_memory_snapshot([(0x02000000, 16), (0x080000A0, 16)])
            assert snapshot.frame == frame
            assert list(snapshot.ranges) == initial_batch
            assert await bridge.advance_frames(0) == frame
            screenshot = await bridge.screenshot()
            assert screenshot.startswith(b"\x89PNG\r\n\x1a\n"), "bridge screenshot is not a PNG"
            await bridge.connect()
            assert await bridge.advance_frames(0) == frame
            checkpoint = tmp_path / f"{mode.value}-checkpoint.ss0"
            assert await bridge.save_state(checkpoint) == frame
            await bridge.advance_frames(17)
            restored_frame = await bridge.load_state(checkpoint)
            assert restored_frame == frame
            assert (
                await bridge.read_memory_batch([(0x02000000, 16), (0x080000A0, 16)])
                == initial_batch
            )
            assert await bridge.advance_frames(0) == frame
            memory_state = await bridge.save_state_buffer()
            await bridge.advance_frames(7)
            assert await bridge.load_state_buffer(memory_state) == frame
            assert (
                await bridge.read_memory_batch([(0x02000000, 16), (0x080000A0, 16)])
                == initial_batch
            )
            if (
                mode is EmulatorMode.WINDOWED
                and os.environ.get("DISPLAY")
                and shutil.which("xdotool")
            ):
                assert launcher.process is not None
                window_output = await asyncio.to_thread(
                    subprocess.check_output,
                    ["xdotool", "search", "--onlyvisible", "--pid", str(launcher.process.pid)],
                    text=True,
                    timeout=5,
                )
                windows = window_output.splitlines()
                assert windows, "the Qt frontend did not map a game window"

                # X maps to the GBA A button in mGBA's default Qt key bindings.
                # A neutral bridge frame must stay neutral while that local key is held.
                await asyncio.to_thread(
                    subprocess.run,
                    ["xdotool", "keydown", "--window", windows[0], "x"],
                    check=True,
                    timeout=5,
                )
                try:
                    await asyncio.sleep(0.1)
                    frame = (frame + 1) % (1 << 32)
                    assert await bridge.advance_frames(1) == frame
                    local_input = await bridge.read_memory_batch([(0x04000130, 2)])
                    assert local_input == [b"\xff\x03"], (
                        "Qt gameplay input reached the core while the frame gate was enabled"
                    )

                    # The same key is accepted when supplied through the bridge.
                    await bridge.set_keys(1)
                    frame = (frame + 1) % (1 << 32)
                    assert await bridge.advance_frames(1) == frame
                    bridge_input = await bridge.read_memory_batch([(0x04000130, 2)])
                    assert bridge_input == [b"\xfe\x03"], (
                        "bridge supplied A input did not reach the emulated core"
                    )
                    await bridge.set_keys(0)
                finally:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["xdotool", "keyup", "--window", windows[0], "x"],
                        check=True,
                        timeout=5,
                    )
                for shortcut in ("ctrl+p", "ctrl+n"):
                    await asyncio.to_thread(
                        subprocess.run,
                        ["xdotool", "key", "--window", windows[0], shortcut],
                        check=True,
                        timeout=5,
                    )
                    await asyncio.sleep(0.2)
                    assert await bridge.advance_frames(0) == frame
            for count in (1, 3, 17, 600):
                frame = (frame + count) % (1 << 32)
                assert await bridge.advance_frames(count) == frame
            await bridge.set_keys(513)
            assert await bridge.advance_frames(0) == frame
            frame = (frame + 3) % (1 << 32)
            assert await bridge.advance_frames(3) == frame
            result = await bridge.request("press_keys", keys=1, frames=3)
            assert result["start_frame"] == frame
            assert result["frames_advanced"] == 3
            assert result["released"] is True
            frame = (frame + 3) % (1 << 32)
            assert result["frame"] == frame
            await asyncio.sleep(0.3)
            assert await bridge.advance_frames(0) == frame
            reset_frame = await bridge.reset()
            assert await bridge.advance_frames(0) == reset_frame
        finally:
            await launcher.stop()
            assert not launcher.is_running

    asyncio.run(check())


@pytest.mark.parametrize("storage", ["file", "buffer"])
def test_checkpoint_restores_in_game_save_data(
    storage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify checkpoint save-data restoration from a local in-mission state."""
    mode = EmulatorMode.WINDOWED
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    default_state_path = (
        Path(__file__).parent / "fixtures" / "save_states" / "aw2-in-game-save-test.ss1"
    )
    state_path = Path(os.environ.get("AW2_TEST_SAVE_STATE_PATH", default_state_path))
    save_path = Path(os.environ.get("AW2_TEST_SAVE_PATH", ""))
    if not rom.is_file():
        pytest.fail("AW2_ROM_PATH must name a local ROM file")
    if not state_path.is_file() or not save_path.is_file():
        pytest.skip(
            "set AW2_TEST_SAVE_STATE_PATH and AW2_TEST_SAVE_PATH to a matching local "
            "in-mission state and cartridge save"
        )
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed mode requires a display")
    executable = os.environ.get(
        f"AW2_TEST_MGBA_{mode.name}",
        "mgba-headless" if mode is EmulatorMode.HEADLESS else "mgba-qt",
    )
    if shutil.which(executable) is None:
        pytest.fail(f"mGBA executable is unavailable: {executable}")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 43128)) == 0:
            pytest.fail("bridge port 43128 is occupied; stop the existing emulator first")

    async def run_session(directory: Path, *, save_and_restore: bool) -> bytes:
        config = directory / "config" / "mgba"
        config.mkdir(parents=True)
        saves = directory / "saves"
        saves.mkdir()
        cartridge_save = saves / f"{rom.stem}.sav"
        shutil.copyfile(save_path, cartridge_save)
        (config / "config.ini").write_text(
            "".join(
                f"[ports.{frontend}]\nsavegamePath={saves}\nsavestatePath={directory}\n"
                for frontend in ("headless", "qt")
            )
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(directory / "config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(directory / "data"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(directory / "cache"))
        (directory / "data").mkdir()
        (directory / "cache").mkdir()

        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom.resolve(),
                mode=mode,
                headless_executable=executable,
                windowed_executable=executable,
                bridge_script=Path(__file__).resolve().parents[1] / "lua" / "bridge.lua",
            )
        )
        bridge = LuaBridgeClient(timeout=1)
        await launcher.start()
        try:
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                assert launcher.is_running, "mGBA exited before the bridge became ready"
                try:
                    await bridge.connect()
                    break
                except BridgeError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(0.05)

            await bridge.load_state(state_path)
            if save_and_restore:
                before = cartridge_save.read_bytes()
                memory_before = await bridge.read_memory_batch([(0x02000000, 16), (0x080000A0, 16)])
                if storage == "file":
                    checkpoint = directory / "checkpoint.ss0"
                    saved_frame = await bridge.save_state(checkpoint)
                else:
                    checkpoint = await bridge.save_state_buffer()
                    saved_frame = await bridge.advance_frames(0)

                # The fixture is in a battle. Open the map menu, choose Save, and
                # confirm the game's save prompt. Neutral frames separate repeated
                # D-pad presses so AW2 observes distinct button edges.
                await bridge.set_keys(4)  # Select: open the map menu.
                await bridge.advance_frames(15)
                await bridge.set_keys(0)
                await bridge.advance_frames(10)
                for _ in range(3):  # CO, Intel, Options, then Save.
                    await bridge.press_keys(128, 1)
                    await bridge.advance_frames(10)
                await bridge.press_keys(1, 1)  # Open Save.
                await bridge.advance_frames(60)
                await bridge.press_keys(1, 1)  # Confirm the in-game save.
                await bridge.advance_frames(60)

                changed = cartridge_save.read_bytes()
                assert changed != before, "the fixture's in-game Save command changed no data"
                if storage == "file":
                    restored_frame = await bridge.load_state(checkpoint)
                else:
                    restored_frame = await bridge.load_state_buffer(checkpoint)
                assert restored_frame == saved_frame
                assert (
                    await bridge.read_memory_batch([(0x02000000, 16), (0x080000A0, 16)])
                    == memory_before
                )
        finally:
            await launcher.stop()
            assert not launcher.is_running
        return cartridge_save.read_bytes()

    async def check() -> None:
        baseline = await run_session(tmp_path / "baseline", save_and_restore=False)
        restored = await run_session(tmp_path / "round-trip", save_and_restore=True)
        assert restored == baseline, "restoring the checkpoint did not restore cartridge save data"

    asyncio.run(check())


def test_windowed_startup_without_display_reports_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    if not rom.is_file():
        pytest.fail("AW2_ROM_PATH must name a local ROM file")
    executable = os.environ.get("AW2_TEST_MGBA_WINDOWED", "mgba-qt")
    if shutil.which(executable) is None:
        pytest.fail(f"mGBA executable is unavailable: {executable}")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom.resolve(),
                mode=EmulatorMode.WINDOWED,
                windowed_executable=executable,
                bridge_script=Path(__file__).resolve().parents[1] / "lua" / "bridge.lua",
                bridge_ready_timeout=5,
            )
        )
        with pytest.raises(EmulatorLaunchError, match="display server"):
            await launcher.start()
        assert not launcher.is_running

    asyncio.run(check())
