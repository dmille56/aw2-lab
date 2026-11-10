"""Opt-in mGBA acceptance for the observed natural Join flow."""

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
from aw2_lab.join_executor import JoinActionExecutor
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, Coordinate, JoinAction, PlayerSlot
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.state_decoder import capture_game_state

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_JOIN_LIVE_TESTS") != "1",
    reason="set AW2_RUN_JOIN_LIVE_TESTS=1 and AW2_ROM_PATH/AW2_JOIN_STATE_PATH",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_join_action(mode: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "~/Downloads/aw2/aw2.gba")).expanduser()
    checkpoint = Path(os.environ.get("AW2_JOIN_STATE_PATH", "~/Downloads/aw2/aw2.ss1")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    assert checkpoint.is_file(), "AW2_JOIN_STATE_PATH must name the ready join checkpoint"
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
            assert initial.ui.menu.family.value == "map_input"
            battle = initial.battle.value
            assert battle is not None
            source = next(
                unit
                for unit in battle.units
                if unit.army_slot == battle.active_player_slot
                and (unit.x, unit.y) == (8, 5)
                and unit.unit_type == 8
            )
            partner = next(
                unit
                for unit in battle.units
                if unit.army_slot == source.army_slot
                and (unit.x, unit.y) == (7, 4)
                and unit.unit_type == source.unit_type
            )
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
            source_id = next(
                identity.identity_id
                for identity in observation.unit_identities
                if identity.reference == source.reference
            )
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=(PlayerSlot.SLOT_1 if source.army_slot == 1 else PlayerSlot.SLOT_2),
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=JoinAction(
                    unit_id=source_id,
                    path=(Coordinate(x=8, y=4), Coordinate(x=7, y=4)),
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
            outcome = await JoinActionExecutor(navigator, tracker).execute(request, observation)
            final = outcome.observation
            assert final is not None
            assert outcome.lifecycle.value == "playable"
            result_battle = final.game_state.battle.value
            assert result_battle is not None
            survivor = next(
                unit for unit in result_battle.units if unit.reference == source.reference
            )
            assert (survivor.x, survivor.y) == (7, 4)
            assert survivor.used_this_turn
            assert survivor.internal_health > source.internal_health
            assert all(unit.reference != partner.reference for unit in result_battle.units)
            after_png = await bridge.screenshot()
            (evidence_dir / "after.png").write_bytes(after_png)
            evidence = {
                "mode": mode,
                "rom_sha256": _sha(rom.read_bytes()),
                "checkpoint_sha256": _sha(checkpoint.read_bytes()),
                "emulator_build": launcher.build_identity,
                "restored_frame": restored_frame,
                "initial_frame": initial.frame,
                "source_reference": source.reference,
                "source_initial_health": source.internal_health,
                "partner_reference": partner.reference,
                "partner_initial_health": partner.internal_health,
                "action_path": [[8, 4], [7, 4]],
                "destination": [7, 4],
                "final_frame": final.game_state.frame,
                "survivor_reference": survivor.reference,
                "survivor_health": survivor.internal_health,
                "partner_removed": True,
                "survivor_used_this_turn": survivor.used_this_turn,
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
            (evidence_dir / "evidence.json").write_text(json.dumps(evidence, indent=2))
        finally:
            await launcher.stop()

    asyncio.run(check())
