"""Opt-in live acceptance for the supplied Sub Dive and Rise checkpoints."""

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
from aw2_lab.match_contract import CommandRequest, DiveAction, PlayerSlot, RiseAction
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.submarine_executor import DiveActionExecutor, RiseActionExecutor
from aw2_lab.ui_state import MenuFamily

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_SUBMARINE_LIVE_TESTS") != "1",
    reason="set AW2_RUN_SUBMARINE_LIVE_TESTS=1 and AW2_ROM_PATH",
)


@pytest.mark.parametrize(
    ("mode", "action_kind", "state_env", "default_state", "before", "after"),
    [
        (mode, "dive", "AW2_DIVE_STATE_PATH", "aw2.ss1", False, True)
        for mode in ("headless", "windowed")
    ]
    + [
        (mode, "rise", "AW2_RISE_STATE_PATH", "aw2.ss6", True, False)
        for mode in ("headless", "windowed")
    ],
)
def test_live_submarine_mode_action(
    mode: str,
    action_kind: str,
    state_env: str,
    default_state: str,
    before: bool,
    after: bool,
    tmp_path: Path,
) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "~/Downloads/aw2/aw2.gba")).expanduser()
    checkpoint = Path(os.environ.get(state_env, f"~/Downloads/aw2/{default_state}")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    assert checkpoint.is_file(), f"{state_env} must name the requested Sub checkpoint"
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
                state = await capture_game_state(bridge, rom_path=rom)
                menu = state.ui.menu
                if (
                    menu.family is MenuFamily.UNIT_ACTION_CHOICES
                    and menu.selected_unit is not None
                    and menu.selected_unit.unit_type == 24
                ):
                    menu_observations.append(
                        {
                            "frame": state.frame,
                            "submerged": menu.selected_unit.submerged,
                            "items": [item.value for item in menu.items],
                        }
                    )
                return state

            menu_observations: list[dict[str, object]] = []
            initial = await observe()
            assert initial.frame == restored_frame
            assert initial.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            assert initial.battle.value is not None
            sub = next(unit for unit in initial.battle.value.units if unit.unit_type == 24)
            assert sub.submerged is before
            assert not sub.used_this_turn and not sub.embarked
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
            identity = next(
                entry.identity_id
                for entry in observation.unit_identities
                if entry.reference == sub.reference
            )
            slot = PlayerSlot.SLOT_1 if sub.army_slot == 1 else PlayerSlot.SLOT_2
            action_type = DiveAction if action_kind == "dive" else RiseAction
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=slot,
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=action_type(unit_id=identity, path=()),
            )
            evidence = tmp_path / f"{mode}-{action_kind}"
            evidence.mkdir()
            (evidence / "before.png").write_bytes(await bridge.screenshot())
            navigator = ActionNavigator(
                bridge,
                observe,
                screenshot_writer=bridge.save_screenshot,
                screenshot_directory=evidence / "navigation-failures",
            )
            executor = (
                DiveActionExecutor(navigator, tracker)
                if after
                else RiseActionExecutor(navigator, tracker)
            )
            outcome = await executor.execute(request, observation)
            assert outcome.observation is not None
            result = outcome.observation.game_state
            assert result.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            assert result.battle.value is not None
            final_sub = next(
                unit for unit in result.battle.value.units if unit.reference == sub.reference
            )
            assert (final_sub.x, final_sub.y) == (sub.x, sub.y)
            assert final_sub.used_this_turn and final_sub.submerged is after
            after_png = await bridge.screenshot()
            (evidence / "after.png").write_bytes(after_png)
            expected_item = "dive" if action_kind == "dive" else "rise"
            assert any(expected_item in menu["items"] for menu in menu_observations)
            before_png = (evidence / "before.png").read_bytes()
            evidence_json = {
                "mode": mode,
                "action": action_kind,
                "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "emulator_build": launcher.build_identity,
                "restored_frame": restored_frame,
                "initial_frame": initial.frame,
                "final_frame": result.frame,
                "sub_reference": sub.reference,
                "start": {
                    "x": sub.x,
                    "y": sub.y,
                    "used": sub.used_this_turn,
                    "submerged": sub.submerged,
                },
                "final": {
                    "x": final_sub.x,
                    "y": final_sub.y,
                    "used": final_sub.used_this_turn,
                    "submerged": final_sub.submerged,
                },
                "sub_menu_observations": menu_observations,
                "before_screenshot_sha256": hashlib.sha256(before_png).hexdigest(),
                "after_screenshot_sha256": hashlib.sha256(after_png).hexdigest(),
            }
            (evidence / "evidence.json").write_text(
                json.dumps(evidence_json, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            await launcher.stop()

    asyncio.run(check())
