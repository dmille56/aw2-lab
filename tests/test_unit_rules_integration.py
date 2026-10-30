"""Opt-in original-ROM checks of indirect actions, fuel debit, and main ammo."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.action_navigation import ActionNavigator, NavigationLimits
from aw2_lab.aw2_unit_profiles import RuleContext, route_cost
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.match_contract import CommandRequest, Coordinate, MoveAttackAction, PlayerSlot
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.move_attack_executor import MoveAttackActionExecutor
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.ui_state import SELECTOR_OBJECT, MenuFamily, MenuItem

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_RULES_LIVE_TESTS") != "1",
    reason="set AW2_RUN_RULES_LIVE_TESTS=1, AW2_ROM_PATH, and AW2_RULES_CHECKPOINT",
)


def test_rockets_movement_fire_and_ammunition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rom = Path(os.environ["AW2_ROM_PATH"]).resolve()
    checkpoint = Path(os.environ["AW2_RULES_CHECKPOINT"]).resolve()
    config = tmp_path / "config" / "mgba"
    config.mkdir(parents=True)
    saves = tmp_path / "saves"
    saves.mkdir()
    (config / "config.ini").write_text(
        f"[ports.headless]\nsavegamePath={saves}\nsavestatePath={saves}\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom,
                mode=EmulatorMode.HEADLESS,
                bridge_script=Path(__file__).resolve().parents[1] / "lua" / "bridge.lua",
                suppress_emulator_output=True,
            )
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None

            # This archived map requires a long cursor approach to the Rockets.
            limits = NavigationLimits(frame_budget=600, wall_timeout=60.0)

            async def observe():
                return await capture_game_state(bridge, rom_path=rom)

            await bridge.load_state(checkpoint)
            await ActionNavigator(bridge, observe, limits=limits).move_cursor_to(10, 5)
            prepared = tmp_path / "rockets-ready.ss0"
            await bridge.save_state(prepared)

            async def restore():
                await bridge.load_state(prepared)
                state = await observe()
                battle = state.battle.value
                assert battle is not None
                unit = next(u for u in battle.units if u.reference == 21)
                assert (unit.unit_type, unit.x, unit.y) == (11, 10, 5)
                assert not unit.used_this_turn
                tracker = MatchObservationTracker(uuid4())
                observation = tracker.commit_boundary(state)
                identity = next(
                    item.identity_id
                    for item in observation.unit_identities
                    if item.reference == unit.reference
                )
                return state, battle, unit, tracker, observation, identity

            # Both the start and moved tile are within the Rockets' firing range.
            initial, battle, unit, _, observation, identity = await restore()
            navigator = ActionNavigator(bridge, observe, limits=limits)
            selected = await navigator.select_unit(identity, observation)
            selected_unit = selected.ui.menu.selected_unit
            assert selected_unit is not None
            ui_identity = (
                selected_unit.army_slot,
                selected_unit.unit_slot,
                selected_unit.unit_type,
                selected_unit.record_address,
            )
            menu = await navigator.move_selected_unit_along_path(
                (), unit=ui_identity, width=battle.map.width, height=battle.map.height
            )
            assert MenuItem.FIRE in menu.ui.menu.items
            (tmp_path / "stationary-fire.png").write_bytes(await bridge.screenshot())
            stationary_items = [item.value for item in menu.ui.menu.items]

            _, battle, unit, _, observation, identity = await restore()
            navigator = ActionNavigator(bridge, observe, limits=limits)
            await navigator.select_unit(identity, observation)
            # AW2 uses a one-choice Wait prompt without an active selector here.
            # Research inputs bypass the production navigator's unresolved prompt;
            # the screenshot and selector state record this explicit coverage gap.
            await bridge.press_keys(0, 2)
            await bridge.press_keys(32, 1)  # Left, onto (9, 5).
            await bridge.press_keys(0, 10)
            await bridge.press_keys(128, 1)  # Down, onto plain (9, 6).
            await bridge.press_keys(0, 10)
            cursor_state = await observe()
            assert cursor_state.ui.menu.family is MenuFamily.UNIT_MOVEMENT
            assert (cursor_state.ui.map_cursor.x, cursor_state.ui.map_cursor.y) == (9, 6)
            await bridge.press_keys(0, 2)
            await bridge.press_keys(1, 1)
            await bridge.press_keys(0, 30)
            for _ in range(20):
                if await bridge.read_memory_batch([(SELECTOR_OBJECT, 4)]) == [bytes(4)]:
                    break
                await bridge.press_keys(0, 10)
            menu = await observe()
            assert menu.ui.menu.family is MenuFamily.UNIT_ACTION
            assert menu.ui.menu.selected_unit is not None
            assert menu.ui.menu.selected_unit.unit_type == 11
            assert await bridge.read_memory_batch([(SELECTOR_OBJECT, 4)]) == [bytes(4)]
            (tmp_path / "moved-no-fire.png").write_bytes(await bridge.screenshot())
            moving_menu_family = menu.ui.menu.family.value
            player = next(p for p in battle.players if p.slot == battle.active_player_slot)
            terrain_by_tile = {(t.x, t.y): t.terrain_class for t in battle.map.tiles}
            terrains = (terrain_by_tile[9, 5], terrain_by_tile[9, 6])
            assert terrains == (5, 1)
            assert battle.weather.value is not None
            cost = route_cost(
                unit.unit_type,
                terrains,
                battle.weather.value,
                context=RuleContext(player.co_id, player.active_power),
            )
            assert cost is not None
            await bridge.press_keys(0, 2)
            await bridge.press_keys(1, 1)  # Confirm the observed one-choice Wait prompt.
            for _ in range(6):
                await bridge.press_keys(0, 30)
                waited = await observe()
                if waited.ui.menu.family is MenuFamily.MAP_INPUT:
                    break
            assert waited.ui.menu.family is MenuFamily.MAP_INPUT
            assert waited.battle.value is not None
            moved = next(u for u in waited.battle.value.units if u.reference == unit.reference)
            assert (moved.x, moved.y) == (9, 6)
            assert moved.fuel == unit.fuel - cost
            assert moved.ammo == unit.ammo
            assert moved.used_this_turn

            _, battle, unit, tracker, observation, identity = await restore()
            target = next(u for u in battle.units if (u.x, u.y) == (13, 6))
            outcome = await MoveAttackActionExecutor(
                ActionNavigator(bridge, observe, limits=limits), tracker
            ).execute(
                CommandRequest(
                    match_id=observation.match_id,
                    player_slot=PlayerSlot.SLOT_1,
                    credential=SecretStr("x" * 32),
                    request_id=uuid4(),
                    expected_revision=observation.revision,
                    action=MoveAttackAction(
                        unit_id=identity, path=(), target=Coordinate(x=13, y=6)
                    ),
                ),
                observation,
            )
            assert outcome.observation is not None
            final = outcome.observation.game_state
            assert final.battle.value is not None
            attacker = next(u for u in final.battle.value.units if u.reference == unit.reference)
            final_target = next(
                (u for u in final.battle.value.units if u.reference == target.reference), None
            )
            assert attacker.ammo == unit.ammo - 1
            assert attacker.fuel == unit.fuel
            assert attacker.used_this_turn
            assert final_target is None or final_target.internal_health < target.internal_health
            evidence = {
                "build_identity": launcher.build_identity,
                "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "initial_frame": initial.frame,
                "stationary_items": stationary_items,
                "moving_menu_family": moving_menu_family,
                "moving_selector_object": 0,
                "entered_terrain": terrains,
                "movement_fuel": [unit.fuel, moved.fuel],
                "predicted_movement_cost": cost,
                "attack_ammo": [unit.ammo, attacker.ammo],
                "target_health": [
                    target.internal_health,
                    None if final_target is None else final_target.internal_health,
                ],
                "final_frame": final.frame,
            }
            (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print(json.dumps(evidence))
        except Exception:
            if launcher.bridge is not None:
                (tmp_path / "failure.png").write_bytes(await launcher.bridge.screenshot())
                await launcher.bridge.save_state(tmp_path / "failure.ss0")
            raise
        finally:
            await launcher.stop()

    asyncio.run(check())
