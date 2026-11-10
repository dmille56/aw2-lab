"""Opt-in cartridge-boot acceptance of every advertised Classic map."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from aw2_lab.cold_boot import boot_fixed_versus_match
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.map_catalog import CLASSIC_MAPS, VersusMap
from aw2_lab.rom_profile import select_rom_profile

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MAP_SELECTION_TESTS") != "1",
    reason="set AW2_RUN_MAP_SELECTION_TESTS=1 and AW2_ROM_PATH for live map selection",
)


@pytest.mark.parametrize("entry", CLASSIC_MAPS, ids=lambda entry: entry.id)
@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_selected_map(entry: VersusMap, mode: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(rom_path=rom, mode=EmulatorMode(mode), suppress_emulator_output=True),
            isolate_saves=True,
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None
            result = await boot_fixed_versus_match(bridge, rom_path=rom, map_id=entry.id)
            battle = result.game_state.battle.value
            assert battle is not None
            assert result.map_id == entry.rom_id
            assert (battle.map.width, battle.map.height) == (entry.width, entry.height)
            assert [(p.slot, p.co_id, p.control_type, p.team_id) for p in battle.players] == [
                (1, 1, 1, 0),
                (2, 2, 1, 1),
            ]
            screenshot = await bridge.screenshot()
            (tmp_path / "ready.png").write_bytes(screenshot)
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "map_id": entry.id,
                        "rom_map_id": result.map_id,
                        "rom_sha256": select_rom_profile(rom).sha256,
                        "build": launcher.build_identity,
                        "mode": mode,
                        "frame": result.game_state.frame,
                        "width": battle.map.width,
                        "height": battle.map.height,
                        "funds": [p.funds for p in battle.players],
                        "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            await launcher.stop()

    asyncio.run(check())


def test_wrong_loaded_map_fails_before_co_setup(tmp_path, monkeypatch):
    """A dropped map-navigation input must never publish the default map instead."""
    from aw2_lab.cold_boot import ColdBootError

    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"

    async def check():
        launcher = EmulatorLauncher(
            EmulatorSettings(rom_path=rom, suppress_emulator_output=True), isolate_saves=True
        )
        labels = []
        skip_map_down = False
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None
            press_keys = bridge.press_keys

            async def record(label, _event):
                nonlocal skip_map_down
                labels.append(label)
                if label == "confirm-versus-new":
                    skip_map_down = True

            async def drop_map_down(keys, frames):
                nonlocal skip_map_down
                if skip_map_down and keys == 128:
                    skip_map_down = False
                    return (await bridge.read_memory_snapshot([(0x03003FC2, 1)])).frame
                return await press_keys(keys, frames)

            monkeypatch.setattr(bridge, "press_keys", drop_map_down)
            with pytest.raises(ColdBootError, match="map confirmation loaded ID 1"):
                await boot_fixed_versus_match(
                    bridge, rom_path=rom, map_id="crater_isle", checkpoint_recorder=record
                )
            assert "select-team-player" not in labels
            (tmp_path / "rejection.json").write_text(json.dumps(labels, indent=2) + "\n")
        finally:
            await launcher.stop()

    asyncio.run(check())
