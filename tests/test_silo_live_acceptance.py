"""Opt-in mGBA acceptance for the supplied missile silo launch checkpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, Coordinate, PlayerSlot, SiloLaunchAction
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.silo_executor import SiloLaunchActionExecutor
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.ui_state import MenuFamily

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_SILO_LIVE_TESTS") != "1",
    reason="set AW2_RUN_SILO_LIVE_TESTS=1 and AW2_ROM_PATH",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_silo_launch(mode: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "~/Downloads/aw2/aw2.gba")).expanduser()
    checkpoint = Path(os.environ.get("AW2_SILO_STATE_PATH", "~/Downloads/aw2/aw2.ss1")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    assert checkpoint.is_file(), "AW2_SILO_STATE_PATH must name the ready silo checkpoint"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom,
                mode=EmulatorMode(mode),
                suppress_emulator_output=True,
            ),
            isolate_saves=True,
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None
            restored_frame = await bridge.load_state(checkpoint)

            async def observe():
                return await capture_game_state(bridge, rom_path=rom)

            initial = await observe()
            assert initial.frame == restored_frame
            assert initial.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            battle = initial.battle.value
            assert battle is not None
            silo_unit = next(
                unit
                for unit in battle.units
                if unit.army_slot == battle.active_player_slot
                and unit.unit_type == 1
                and (unit.x, unit.y) == (3, 16)
            )
            silo = next(tile for tile in battle.map.tiles if (tile.x, tile.y) == (3, 16))
            assert silo.terrain_class == 17
            enemies_before = {
                (unit.x, unit.y): unit.internal_health
                for unit in battle.units
                if unit.army_slot != battle.active_player_slot
                and abs(unit.x - 2) <= 1
                and abs(unit.y - 13) <= 1
            }
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
            identity = next(
                entry.identity_id
                for entry in observation.unit_identities
                if entry.reference == silo_unit.reference
            )
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=(PlayerSlot.SLOT_1 if silo_unit.army_slot == 1 else PlayerSlot.SLOT_2),
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=SiloLaunchAction(
                    unit_id=identity,
                    path=(),
                    target=Coordinate(x=2, y=13),
                ),
            )
            evidence_dir = tmp_path / mode
            evidence_dir.mkdir()
            before_png = await bridge.screenshot()
            (evidence_dir / "before.png").write_bytes(before_png)
            navigator = ActionNavigator(
                bridge,
                observe,
                screenshot_writer=bridge.save_screenshot,
                screenshot_directory=evidence_dir / "navigation-failures",
            )
            outcome = await SiloLaunchActionExecutor(navigator, tracker).execute(
                request, observation
            )
            final = outcome.observation
            assert final is not None
            result = final.game_state
            result_battle = result.battle.value
            assert result.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            assert result.ui.menu.family is MenuFamily.MAP_INPUT
            assert result_battle is not None
            final_unit = next(
                unit for unit in result_battle.units if unit.reference == silo_unit.reference
            )
            final_tile = next(
                tile for tile in result_battle.map.tiles if (tile.x, tile.y) == (3, 16)
            )
            assert (final_unit.x, final_unit.y) == (3, 16)
            assert final_unit.used_this_turn
            assert final_tile.terrain_class == 18
            enemies_after = {
                (unit.x, unit.y): unit.internal_health
                for unit in result_battle.units
                if unit.army_slot != result_battle.active_player_slot
                and abs(unit.x - 2) <= 1
                and abs(unit.y - 13) <= 1
            }
            damaged = {
                f"{x},{y}": {"before": health, "after": enemies_after[(x, y)]}
                for (x, y), health in enemies_before.items()
                if (x, y) in enemies_after and enemies_after[(x, y)] < health
            }
            assert damaged, "The 3x3 missile blast should damage at least one enemy in this state"
            after_png = await bridge.screenshot()
            (evidence_dir / "after.png").write_bytes(after_png)
            evidence = {
                "mode": mode,
                "rom_sha256": _sha(rom.read_bytes()),
                "checkpoint_sha256": _sha(checkpoint.read_bytes()),
                "emulator_build": launcher.build_identity,
                "restored_frame": restored_frame,
                "initial_frame": initial.frame,
                "final_frame": result.frame,
                "unit_reference": silo_unit.reference,
                "silo": {"coordinate": [3, 16], "terrain_before": 17, "terrain_after": 18},
                "target": [2, 13],
                "blast_damage": damaged,
                "unit_used_this_turn": final_unit.used_this_turn,
                "inputs": [
                    {
                        "name": event.name,
                        "keys": event.keys,
                        "frames": event.frames,
                        "start_frame": event.start_frame,
                        "end_frame": event.end_frame,
                    }
                    for event in navigator.inputs
                ],
                "before_png_sha256": _sha(before_png),
                "after_png_sha256": _sha(after_png),
                "passed": True,
            }
            (evidence_dir / "evidence.json").write_text(
                json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            await launcher.stop()

    asyncio.run(check())
