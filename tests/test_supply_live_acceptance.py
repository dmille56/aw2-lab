"""Opt-in mGBA acceptance for APC Supply in both emulator frontends."""

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
from aw2_lab.end_turn_executor import EndTurnActionExecutor
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    Coordinate,
    EndTurnAction,
    GameplayAction,
    MatchLifecycle,
    MoveWaitAction,
    PlayerSlot,
    PurchaseAction,
    SupplyAction,
)
from aw2_lab.match_observation import MatchObservation, MatchObservationTracker
from aw2_lab.move_wait_executor import MoveWaitActionExecutor
from aw2_lab.purchase_executor import PurchaseActionExecutor
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.supply_executor import SupplyActionExecutor
from aw2_lab.ui_state import MenuFamily

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_SUPPLY_LIVE_TESTS") != "1",
    reason="set AW2_RUN_SUPPLY_LIVE_TESTS=1 and AW2_SUPPLY_STATE_PATH",
)

_STAGING_PATH = tuple(
    Coordinate(x=x, y=y) for x, y in ((3, 7), (3, 8), (3, 9), (4, 9), (5, 9), (5, 8))
)
_SUPPLY_PATH = tuple(Coordinate(x=x, y=y) for x, y in ((5, 7), (5, 6), (5, 5), (5, 4), (6, 4)))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _request(observation: MatchObservation, action: GameplayAction) -> CommandRequest:
    battle = observation.game_state.battle.value
    assert battle is not None
    slot = PlayerSlot.SLOT_1 if battle.active_player_slot == 1 else PlayerSlot.SLOT_2
    return CommandRequest(
        match_id=observation.match_id,
        player_slot=slot,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=observation.revision,
        action=action,
    )


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_apc_supply(mode: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "~/Downloads/aw2/aw2.gba")).expanduser()
    checkpoint = Path(
        os.environ.get("AW2_SUPPLY_STATE_PATH", "~/Downloads/aw2/aw2.ss1")
    ).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    assert checkpoint.is_file(), "AW2_SUPPLY_STATE_PATH must name the ready battle checkpoint"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check() -> None:
        evidence_dir = tmp_path / mode
        evidence_dir.mkdir()
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
            observed_supply_menus: list[tuple[str, ...]] = []
            observed_apc_menu_signatures: set[tuple[str, tuple[str, ...]]] = set()

            async def observe():
                state = await capture_game_state(bridge, rom_path=rom)
                menu = state.ui.menu
                if (
                    menu.family is MenuFamily.UNIT_ACTION_CHOICES
                    and menu.selected_unit is not None
                    and menu.selected_unit.unit_type == 7
                ):
                    observed_supply_menus.append(tuple(item.value for item in menu.items))
                if menu.selected_unit is not None and menu.selected_unit.unit_type == 7:
                    signature = (menu.family.value, tuple(item.value for item in menu.items))
                    if signature not in observed_apc_menu_signatures:
                        observed_apc_menu_signatures.add(signature)
                        if os.environ.get("AW2_SUPPLY_DEBUG") == "1":
                            print("APC menu observation", state.frame, signature, menu.reasons)
                return state

            initial = await observe()
            assert initial.frame == restored_frame
            assert initial.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            assert initial.ui.menu.family is MenuFamily.MAP_INPUT
            assert initial.battle.value is not None
            assert initial.battle.value.active_player_slot == 1
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
            navigator = ActionNavigator(
                bridge,
                observe,
                screenshot_writer=bridge.save_screenshot,
                screenshot_directory=evidence_dir / "navigation-failures",
            )

            # Prepare a real APC using only game menus, then bring it around the
            # mountain ridge to a ready turn near two damaged-supply allies.
            purchased = await PurchaseActionExecutor(navigator, tracker).execute(
                _request(
                    observation,
                    PurchaseAction(property=Coordinate(x=3, y=6), unit_type="APC"),
                ),
                observation,
            )
            assert purchased.observation is not None
            observation = purchased.observation
            purchased_battle = observation.game_state.battle.value
            assert purchased_battle is not None
            apc = next(
                unit
                for unit in purchased_battle.units
                if unit.army_slot == 1 and unit.unit_type == 7 and (unit.x, unit.y) == (3, 6)
            )
            apc_id = next(
                item.identity_id
                for item in observation.unit_identities
                if item.reference == apc.reference
            )
            for _ in range(2):
                ended = await EndTurnActionExecutor(navigator, tracker).execute(
                    _request(observation, EndTurnAction()), observation
                )
                assert ended.observation is not None
                observation = ended.observation
            staged = await MoveWaitActionExecutor(navigator, tracker).execute(
                _request(observation, MoveWaitAction(unit_id=apc_id, path=_STAGING_PATH)),
                observation,
            )
            assert staged.observation is not None
            observation = staged.observation
            for _ in range(2):
                ended = await EndTurnActionExecutor(navigator, tracker).execute(
                    _request(observation, EndTurnAction()), observation
                )
                assert ended.observation is not None
                observation = ended.observation

            battle = observation.game_state.battle.value
            assert battle is not None
            assert observation.game_state.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
            assert battle.active_player_slot == 1
            apc = next(unit for unit in battle.units if unit.reference == apc.reference)
            assert (apc.x, apc.y) == (5, 8)
            assert not apc.used_this_turn
            low_supply_allies = [
                unit
                for unit in battle.units
                if unit.army_slot == 1
                and unit.unit_type == 8
                and (unit.x, unit.y) in ((6, 5), (7, 4))
            ]
            assert len(low_supply_allies) == 2
            assert any(unit.ammo < 9 for unit in low_supply_allies)
            assert any(unit.fuel < 99 for unit in low_supply_allies)
            setup_checkpoint = evidence_dir / "apc-ready-before-supply.ss1"
            await bridge.save_state(setup_checkpoint)
            before_png = await bridge.screenshot()
            (evidence_dir / "before.png").write_bytes(before_png)
            before_units = {
                unit.reference: {"fuel": unit.fuel, "ammo": unit.ammo} for unit in low_supply_allies
            }
            outcome = await SupplyActionExecutor(navigator, tracker).execute(
                _request(
                    observation,
                    SupplyAction(
                        unit_id=apc_id,
                        path=_SUPPLY_PATH,
                    ),
                ),
                observation,
            )
            assert outcome.lifecycle is MatchLifecycle.PLAYABLE
            assert outcome.observation is not None
            final = outcome.observation.game_state
            final_battle = final.battle.value
            assert final_battle is not None
            assert any("supply" in menu for menu in observed_supply_menus)
            final_apc = next(unit for unit in final_battle.units if unit.reference == apc.reference)
            assert (final_apc.x, final_apc.y) == (6, 4)
            assert final_apc.used_this_turn
            recipient_results = []
            for old in low_supply_allies:
                new = next(unit for unit in final_battle.units if unit.reference == old.reference)
                assert new.fuel == 99
                assert new.ammo == 9
                recipient_results.append(
                    {
                        "reference": new.reference,
                        "unit_type": new.unit_type,
                        "before": before_units[new.reference],
                        "after": {"fuel": new.fuel, "ammo": new.ammo},
                    }
                )
            after_png = await bridge.screenshot()
            (evidence_dir / "after.png").write_bytes(after_png)
            evidence = {
                "mode": mode,
                "rom_sha256": _sha(rom.read_bytes()),
                "checkpoint_sha256": _sha(checkpoint.read_bytes()),
                "apc_ready_checkpoint_sha256": _sha(setup_checkpoint.read_bytes()),
                "emulator_build": launcher.build_identity,
                "restored_frame": restored_frame,
                "supply_start_frame": observation.game_state.frame,
                "staged_apc_position": [apc.x, apc.y],
                "action_path": [[point.x, point.y] for point in _SUPPLY_PATH],
                "supply_menu_items": observed_supply_menus,
                "final_frame": final.frame,
                "final_apc_position": [final_apc.x, final_apc.y],
                "final_apc_used": final_apc.used_this_turn,
                "recipients": recipient_results,
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
