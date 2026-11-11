"""Opt-in mGBA acceptance of all COs in both player slots and launch modes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from aw2_lab.cold_boot import boot_fixed_versus_match
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.match_contract import CO_ID_VALUES
from aw2_lab.rom_profile import select_rom_profile

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_CO_SELECTION_TESTS") != "1",
    reason="set AW2_RUN_CO_SELECTION_TESTS=1 and AW2_ROM_PATH for live CO selection",
)


@pytest.mark.parametrize("mode", ("headless", "windowed"))
@pytest.mark.parametrize("co_index", range(len(CO_ID_VALUES)))
def test_live_selected_cos(mode: str, co_index: int, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")
    co_ids = (
        CO_ID_VALUES[co_index],
        CO_ID_VALUES[(co_index + 1) % len(CO_ID_VALUES)],
    )
    source_save = rom.with_suffix(".sav")
    source_hash = (
        hashlib.sha256(source_save.read_bytes()).hexdigest() if source_save.is_file() else None
    )

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(rom_path=rom, mode=EmulatorMode(mode), suppress_emulator_output=True),
            isolate_saves=True,
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None
            result = await boot_fixed_versus_match(
                bridge, rom_path=rom, co_ids=co_ids, save_mode="existing"
            )
            battle = result.game_state.battle.value
            assert battle is not None
            actual = {player.slot: player.co_id for player in battle.players}
            battle_ids = {
                0: 0,
                1: 1,
                2: 2,
                3: 4,
                4: 15,
                5: 3,
                6: 5,
                7: 16,
                8: 6,
                9: 7,
                10: 18,
                11: 8,
                12: 9,
                13: 17,
                14: 11,
                15: 12,
                16: 13,
                17: 14,
                18: 10,
            }
            expected = {
                slot: battle_ids[CO_ID_VALUES.index(co_id)] for slot, co_id in enumerate(co_ids, 1)
            }
            assert actual == expected
            screenshot = await bridge.screenshot()
            (tmp_path / "ready.png").write_bytes(screenshot)
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "co_ids": co_ids,
                        "rom_sha256": select_rom_profile(rom).sha256,
                        "build": launcher.build_identity,
                        "mode": mode,
                        "frame": result.game_state.frame,
                        "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
                        "source_save_sha256": source_hash,
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            await launcher.stop()

    asyncio.run(check())
    if source_hash is not None:
        assert hashlib.sha256(source_save.read_bytes()).hexdigest() == source_hash
