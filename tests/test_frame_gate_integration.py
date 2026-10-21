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
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings

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
