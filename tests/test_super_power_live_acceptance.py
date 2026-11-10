"""Opt-in real-emulator acceptance for the guarded Super Power action."""

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
from aw2_lab.match_contract import (
    ActivateSuperPowerAction,
    CommandRequest,
    MatchLifecycle,
    PlayerSlot,
)
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.power_executor import ActivateSuperPowerActionExecutor
from aw2_lab.state_decoder import capture_game_state

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_SUPER_POWER_LIVE_TESTS") != "1",
    reason="set AW2_RUN_SUPER_POWER_LIVE_TESTS=1 and AW2_ROM_PATH/AW2_SUPER_POWER_STATE_PATH",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_super_power_action(mode, tmp_path):
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    checkpoint = Path(os.environ.get("AW2_SUPER_POWER_STATE_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    assert checkpoint.is_file(), "AW2_SUPER_POWER_STATE_PATH must name the ready checkpoint"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check():
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
            assert battle.active_player_slot == 1
            player = next(item for item in battle.players if item.slot == 1)
            assert player.co_id == 1
            assert player.active_power == 0
            assert player.power_meter.value == 54_000
            assert player.power_use_counter.value == 0

            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
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
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=PlayerSlot.SLOT_1,
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=ActivateSuperPowerAction(),
            )
            outcome = await ActivateSuperPowerActionExecutor(navigator, tracker, rom).execute(
                request, observation
            )
            assert outcome.lifecycle is MatchLifecycle.PLAYABLE
            assert outcome.observation is not None
            final = outcome.observation.game_state
            assert final.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            final_player = next(item for item in final.battle.value.players if item.slot == 1)
            assert final_player.active_power == 2
            assert final_player.power_meter.value == 0
            assert final_player.power_use_counter.value == 1
            after_png = await bridge.screenshot()
            (evidence_dir / "after.png").write_bytes(after_png)
            evidence = {
                "mode": mode,
                "rom_sha256": _sha(rom.read_bytes()),
                "checkpoint_sha256": _sha(checkpoint.read_bytes()),
                "emulator_build": launcher.build_identity,
                "restored_frame": restored_frame,
                "initial_frame": initial.frame,
                "initial_co_id": player.co_id,
                "initial_meter": player.power_meter.value,
                "activation_threshold": 54_000,
                "deduction_threshold_after_counter_increment": 64_800,
                "final_frame": final.frame,
                "final_meter": final_player.power_meter.value,
                "final_use_counter": final_player.power_use_counter.value,
                "final_active_power": final_player.active_power,
                "inputs": [
                    event.__dict__
                    if hasattr(event, "__dict__")
                    else {
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
