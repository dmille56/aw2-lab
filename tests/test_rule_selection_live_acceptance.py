"""Opt-in live acceptance of non-default Versus Rules-screen choices."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from aw2_lab.cold_boot import boot_fixed_versus_match
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.match_contract import MatchRules
from aw2_lab.rom_profile import select_rom_profile

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_RULE_SELECTION_TESTS") != "1",
    reason="set AW2_RUN_RULE_SELECTION_TESTS=1 and AW2_ROM_PATH for live rule acceptance",
)


@pytest.mark.parametrize("mode", ("headless", "windowed"))
@pytest.mark.parametrize("weather", ("random", "clear", "rain", "snow"))
def test_live_configurable_rules(mode: str, weather: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")
    source_save = rom.with_suffix(".sav")
    source_hash = hashlib.sha256(source_save.read_bytes()).hexdigest()
    selected_rules = MatchRules(
        day_limit=None,
        starting_funds=2000,
        capture_limit=20,
        co_powers=False,
        starting_weather=weather,
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

            async def record_checkpoint(label: str, _input: dict[str, int] | None) -> None:
                if label == "verified-configurable-rules":
                    (tmp_path / "rules.png").write_bytes(await bridge.screenshot())

            result = await boot_fixed_versus_match(
                bridge,
                rom_path=rom,
                save_mode="existing",
                match_rules=selected_rules,
                checkpoint_recorder=record_checkpoint,
            )
            battle = result.game_state.battle.value
            assert battle is not None
            assert battle.co_effects_enabled.value is False
            red_income_properties = sum(
                prop.owner_slot == 1 and prop.terrain_class in (6, 8, 10, 11, 14)
                for prop in battle.properties
            )
            assert battle.players[0].funds == red_income_properties * 2000
            screenshot = await bridge.screenshot()
            (tmp_path / "ready.png").write_bytes(screenshot)
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "rules": selected_rules.model_dump(mode="json"),
                        "rom_sha256": select_rom_profile(rom).sha256,
                        "build": launcher.build_identity,
                        "mode": mode,
                        "frame": result.game_state.frame,
                        "rules_screenshot_sha256": hashlib.sha256(
                            (tmp_path / "rules.png").read_bytes()
                        ).hexdigest(),
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
    assert hashlib.sha256(source_save.read_bytes()).hexdigest() == source_hash
