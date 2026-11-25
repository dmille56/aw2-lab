"""Opt-in mGBA acceptance of all COs in both player slots and launch modes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.api_contract import default_players
from aw2_lab.cold_boot import boot_fixed_versus_match
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.end_turn_executor import EndTurnActionExecutor
from aw2_lab.map_catalog import MAPS_BY_ID
from aw2_lab.match_contract import (
    CO_ID_VALUES,
    AttackAction,
    CommandRequest,
    Coordinate,
    EndTurnAction,
    FixedMatchConfiguration,
    MatchLifecycle,
    MatchRules,
    MoveCaptureAction,
    MoveWaitAction,
    PlayerSlot,
    PurchaseAction,
    SurrenderAction,
)
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.move_attack_executor import MoveAttackActionExecutor
from aw2_lab.move_capture_executor import MoveCaptureActionExecutor
from aw2_lab.move_wait_executor import MoveWaitActionExecutor
from aw2_lab.purchase_executor import PurchaseActionExecutor
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.surrender_executor import SurrenderActionExecutor

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MULTIPLAYER_TESTS") != "1",
    reason="set AW2_RUN_MULTIPLAYER_TESTS=1 and AW2_ROM_PATH for live CO selection",
)


@pytest.mark.parametrize("mode", ("headless", "windowed"))
@pytest.mark.parametrize(
    "map_id",
    ("bean_island", "pyramid_cape", "four_corners", "delta_heights", "coil_range", "stamp_islands"),
)
def test_live_multiplayer_setup(mode: str, map_id: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")
    co_ids = tuple(p.co_id for p in default_players(MAPS_BY_ID[map_id].player_count))
    team_ids = (0, 1) if len(co_ids) == 2 else (0, 1, 1) if len(co_ids) == 3 else (0, 0, 1, 1)
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
                bridge,
                rom_path=rom,
                co_ids=co_ids,
                team_ids=team_ids,
                map_id=map_id,
                save_mode="existing",
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
            assert tuple(p.team_id for p in battle.players) == team_ids
            assert all(p.control_type == 1 for p in battle.players)
            screenshot = await bridge.screenshot()
            (tmp_path / "ready.png").write_bytes(screenshot)
            if map_id in ("pyramid_cape", "four_corners"):
                tracker = MatchObservationTracker(uuid4())
                observation = tracker.commit_boundary(result.game_state)

                async def observe():
                    return await capture_game_state(bridge, rom_path=rom)

                executor = EndTurnActionExecutor(ActionNavigator(bridge, observe), tracker)
                for index in range(len(co_ids)):
                    request = CommandRequest(
                        match_id=observation.match_id,
                        player_slot=PlayerSlot(f"slot_{index + 1}"),
                        credential=SecretStr("x" * 43),
                        request_id=uuid4(),
                        expected_revision=observation.revision,
                        action=EndTurnAction(),
                    )
                    outcome = await executor.execute(request, observation)
                    observation = outcome.observation
                    assert (
                        observation.game_state.battle.value.active_player_slot
                        == (index + 1) % len(co_ids) + 1
                    )
                assert observation.game_state.battle.value.day == 2
                if map_id == "four_corners":
                    request = CommandRequest(
                        match_id=observation.match_id,
                        player_slot=PlayerSlot.SLOT_1,
                        credential=SecretStr("x" * 43),
                        request_id=uuid4(),
                        expected_revision=observation.revision,
                        action=SurrenderAction(),
                    )
                    yielded = await SurrenderActionExecutor(executor.navigator, tracker).execute(
                        request, observation
                    )
                    assert yielded.lifecycle is MatchLifecycle.PLAYABLE
                    assert yielded.observation.game_state.battle.value.active_player_slot == 2
                    observation = yielded.observation
                    for current, following in ((2, 3), (3, 4), (4, 2)):
                        request = CommandRequest(
                            match_id=observation.match_id,
                            player_slot=PlayerSlot(f"slot_{current}"),
                            credential=SecretStr("x" * 43),
                            request_id=uuid4(),
                            expected_revision=observation.revision,
                            action=EndTurnAction(),
                        )
                        observation = (await executor.execute(request, observation)).observation
                        assert observation.game_state.battle.value.active_player_slot == following
                    assert observation.game_state.battle.value.day == 3

            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "co_ids": co_ids,
                        "map_id": map_id,
                        "team_ids": team_ids,
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


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("two_army_draw", ("draw", "draw")),
        ("team_draw", ("draw", "draw", "draw", "draw")),
        ("shared_win", ("win", "win", "loss", "loss")),
        ("team_yield", ("win", "win", "loss", "loss")),
        ("rout", ("loss", "win")),
    ],
)
def test_live_versus_results(case, expected):
    rom = Path(os.environ["AW2_ROM_PATH"]).expanduser()
    four_armies = len(expected) == 4
    allied = case in {"team_draw", "team_yield"}
    config = FixedMatchConfiguration(
        map_id="four_corners" if four_armies else "bean_island",
        player_2_team="a" if allied else "b",
        player_3_co="andy" if four_armies else None,
        player_4_co="max" if four_armies else None,
        player_3_team="b" if allied else "c",
        player_4_team="b" if allied else "d",
        rules=MatchRules(day_limit=None if case in {"team_yield", "rout"} else 5),
    )

    async def check():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        launcher = EmulatorLauncher(
            EmulatorSettings(rom_path=rom, bridge_port=port, suppress_emulator_output=True),
            isolate_saves=True,
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            boot = await boot_fixed_versus_match(
                bridge,
                rom_path=rom,
                map_id=config.map_id,
                co_ids=config.co_ids,
                team_ids=config.team_ids,
                match_rules=config.rules,
                fresh_roster=True,
                save_mode="existing",
            )
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(boot.game_state)

            async def observe():
                return await capture_game_state(bridge, rom_path=rom, versus=config)

            navigator = ActionNavigator(bridge, observe)

            async def command(action, executor):
                nonlocal observation
                battle = observation.game_state.battle.value
                request = CommandRequest(
                    match_id=observation.match_id,
                    player_slot=PlayerSlot(f"slot_{battle.active_player_slot}"),
                    credential=SecretStr("x" * 43),
                    request_id=uuid4(),
                    expected_revision=observation.revision,
                    action=action,
                )
                outcome = await executor(navigator, tracker).execute(request, observation)
                observation = outcome.observation
                return outcome.lifecycle

            def unit_id(slot):
                battle = observation.game_state.battle.value
                unit = next(u for u in battle.units if u.army_slot == slot)
                return next(
                    item.identity_id
                    for item in observation.unit_identities
                    if item.reference == unit.reference
                )

            if case == "team_yield":
                # The first player yields, but their teammate goes on to win.
                assert (
                    await command(SurrenderAction(), SurrenderActionExecutor)
                    is MatchLifecycle.PLAYABLE
                )
                await command(EndTurnAction(), EndTurnActionExecutor)
                assert (
                    await command(SurrenderAction(), SurrenderActionExecutor)
                    is MatchLifecycle.PLAYABLE
                )
                lifecycle = await command(SurrenderAction(), SurrenderActionExecutor)
            elif case == "rout":
                target = Coordinate(x=1, y=8)
                await command(
                    PurchaseAction(property=target, unit_type="Infantry"), PurchaseActionExecutor
                )
                await command(EndTurnAction(), EndTurnActionExecutor)
                await command(
                    PurchaseAction(property=Coordinate(x=12, y=6), unit_type="Tank"),
                    PurchaseActionExecutor,
                )
                tank = unit_id(2)
                for route in (
                    ((12, 7), (12, 8), (12, 9), (11, 9), (10, 9), (9, 9)),
                    ((9, 8), (9, 7), (9, 6), (9, 5), (8, 5), (7, 5)),
                    ((6, 5), (5, 5), (5, 6), (5, 7), (5, 8), (5, 9)),
                    ((4, 9), (3, 9), (2, 9), (1, 9)),
                ):
                    await command(EndTurnAction(), EndTurnActionExecutor)
                    await command(EndTurnAction(), EndTurnActionExecutor)
                    await command(
                        MoveWaitAction(
                            unit_id=tank, path=tuple(Coordinate(x=x, y=y) for x, y in route)
                        ),
                        MoveWaitActionExecutor,
                    )
                for _ in range(2):
                    await command(EndTurnAction(), EndTurnActionExecutor)
                    await command(EndTurnAction(), EndTurnActionExecutor)
                    lifecycle = await command(
                        AttackAction(unit_id=tank, target=target), MoveAttackActionExecutor
                    )
                    if lifecycle is MatchLifecycle.FINISHED:
                        break
            else:
                for _ in range(5 * len(expected)):
                    battle = observation.game_state.battle.value
                    slot, day = battle.active_player_slot, battle.day
                    if case == "shared_win" and slot in (1, 2) and day < 4:
                        base, route = (
                            ((0, 8), ((1, 8), (2, 8), (3, 8)))
                            if slot == 1
                            else ((13, 9), ((12, 9), (11, 9), (11, 8)))
                        )
                        if day == 1:
                            await command(
                                PurchaseAction(
                                    property=Coordinate(x=base[0], y=base[1]), unit_type="Infantry"
                                ),
                                PurchaseActionExecutor,
                            )
                        else:
                            path = tuple(Coordinate(x=x, y=y) for x, y in route) if day == 2 else ()
                            await command(
                                MoveCaptureAction(unit_id=unit_id(slot), path=path),
                                MoveCaptureActionExecutor,
                            )
                    lifecycle = await command(EndTurnAction(), EndTurnActionExecutor)
                    if lifecycle is MatchLifecycle.FINISHED:
                        break
            assert lifecycle is MatchLifecycle.FINISHED
            terminal = observation.game_state
            assert tuple(result.outcome for result in terminal.versus_result) == expected
            checkpoint = await bridge.save_state_buffer()
            await bridge.advance_frames(120)
            await bridge.load_state_buffer(checkpoint)
            restored = await observe()
            assert restored.frame == terminal.frame
            assert restored.versus_result == terminal.versus_result
        finally:
            await launcher.stop()

    asyncio.run(check())
