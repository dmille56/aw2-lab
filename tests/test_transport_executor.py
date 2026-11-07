"""ROM-independent transport action validation and orchestration checks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.aw2_unit_profiles import BASELINE_RULES, UNIT_PROFILES, movement_cost
from aw2_lab.match_contract import (
    CargoDrop,
    CommandRequest,
    Coordinate,
    PlayerSlot,
    UnloadAction,
)
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import ObservedValue, ValueStatus, Weather
from aw2_lab.transport_executor import UnloadActionExecutor
from aw2_lab.ui_state import MenuFamily, MenuItem, MenuObservation, SelectedUnitObservation


def _setup(memory, *, carrier_type=7, cargo_types=(1,)):
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    decoded = decode_snapshot(snapshot(memory))
    battle = decoded.battle.value
    assert battle is not None
    active = next(unit for unit in battle.units if unit.army_slot == battle.active_player_slot)
    other = next(unit for unit in battle.units if unit.reference != active.reference)
    cargo = replace(
        other,
        army_slot=active.army_slot,
        unit_slot=active.unit_slot + 1,
        unit_type=cargo_types[0],
        x=active.x,
        y=active.y,
        used_this_turn=True,
        embarked=True,
        cargo_references=(),
    )
    cargoes = [cargo]
    cargoes.extend(
        replace(
            cargo,
            reference=2,
            unit_slot=active.unit_slot + index + 1,
            unit_type=unit_type,
        )
        for index, unit_type in enumerate(cargo_types[1:])
    )
    carrier = replace(
        active,
        unit_type=carrier_type,
        used_this_turn=False,
        embarked=False,
        cargo_references=tuple(item.reference for item in cargoes),
    )
    battle = replace(
        battle,
        weather=ObservedValue(ValueStatus.AVAILABLE, Weather.CLEAR),
        co_effects_enabled=ObservedValue(ValueStatus.AVAILABLE, False),
        units=tuple(
            carrier
            if unit.reference == active.reference
            else cargo
            if unit.reference == other.reference
            else unit
            for unit in battle.units
        )
        + tuple(cargoes[1:]),
    )
    decoded = replace(decoded, battle=replace(decoded.battle, value=battle))
    initial = tracker.commit_boundary(decoded)
    legal_tiles = [
        tile
        for tile in battle.map.tiles
        if (tile.x, tile.y) != (carrier.x, carrier.y)
        and all(
            movement_cost(
                tile.terrain_class,
                UNIT_PROFILES[item.unit_type].movement_type,
                Weather.CLEAR,
                context=BASELINE_RULES,
            )
            is not None
            for item in cargoes
        )
    ]
    assert len(legal_tiles) >= len(cargoes)
    destinations = tuple((tile.x, tile.y) for tile in legal_tiles[: len(cargoes)])
    carrier_identity = next(
        identity.identity_id
        for identity in initial.unit_identities
        if identity.reference == carrier.reference
    )
    cargo_identities = tuple(
        next(
            identity.identity_id
            for identity in initial.unit_identities
            if identity.reference == item.reference
        )
        for item in cargoes
    )
    return (
        tracker,
        initial,
        carrier,
        tuple(cargoes),
        carrier_identity,
        cargo_identities,
        destinations,
    )


def _game_state_at(initial, frame, battle, menu):
    state = initial
    return replace(
        state,
        frame=frame,
        validation=replace(state.validation, frame=frame),
        battle=replace(state.battle, value=battle),
        ui=replace(
            state.ui,
            frame=frame,
            map_cursor=replace(state.ui.map_cursor, frame=frame),
            menu=replace(menu, frame=frame),
        ),
    )


@pytest.mark.parametrize(
    ("carrier_type", "cargo_types"), [(7, (1,)), (23, (1, 5))], ids=("apc", "lander-two")
)
def test_unload_drops_named_cargo_and_commits_identity_stable_state(
    memory, carrier_type, cargo_types
) -> None:
    tracker, initial, carrier, cargoes, carrier_id, cargo_ids, destinations = _setup(
        memory, carrier_type=carrier_type, cargo_types=cargo_types
    )
    match_id = initial.match_id
    battle = initial.game_state.battle.value
    assert battle is not None
    carrier_selected = SelectedUnitObservation(
        0x02022684 + carrier.reference * 12,
        carrier.army_slot,
        carrier.unit_slot,
        carrier.unit_type,
        carrier.x,
        carrier.y,
    )
    action_menu = MenuObservation(
        124,
        MenuFamily.UNIT_ACTION_CHOICES,
        selected_unit=carrier_selected,
        selected_item=MenuItem.UNLOAD,
        actionable=True,
        items=(MenuItem.UNLOAD, MenuItem.WAIT),
    )
    after_drop_states = []
    for index in range(len(cargoes)):
        remaining = tuple(item.reference for item in cargoes[index + 1 :])
        units = []
        for unit in battle.units:
            if unit.reference == carrier.reference:
                units.append(replace(carrier, used_this_turn=True, cargo_references=remaining))
            elif any(item.reference == unit.reference for item in cargoes[: index + 1]):
                cargo_index = next(
                    i
                    for i, item in enumerate(cargoes[: index + 1])
                    if item.reference == unit.reference
                )
                destination = destinations[cargo_index]
                units.append(
                    replace(
                        unit,
                        x=destination[0],
                        y=destination[1],
                        embarked=False,
                        used_this_turn=True,
                    )
                )
            else:
                units.append(unit)
        intermediate_battle = replace(battle, units=tuple(units))
        rows = (MenuItem.UNLOAD, MenuItem.WAIT) if remaining else (MenuItem.WAIT,)
        menu_after_drop = (
            MenuObservation(125 + index, MenuFamily.MAP_INPUT)
            if carrier_type == 7 and not remaining
            else replace(action_menu, items=rows, selected_item=rows[0])
        )
        after_drop_states.append(
            _game_state_at(
                initial.game_state,
                125 + index,
                intermediate_battle,
                menu_after_drop,
            )
        )
    final_battle = after_drop_states[-1].battle.value
    assert final_battle is not None
    final_state = _game_state_at(
        initial.game_state,
        125 + len(cargoes),
        final_battle,
        MenuObservation(125 + len(cargoes), MenuFamily.MAP_INPUT),
    )
    assert final_state.battle.value is not None
    landed_carrier = next(
        unit for unit in final_state.battle.value.units if unit.reference == carrier.reference
    )
    assert landed_carrier.used_this_turn and not landed_carrier.cargo_references
    for index, cargo in enumerate(cargoes):
        landed = next(
            unit for unit in final_state.battle.value.units if unit.reference == cargo.reference
        )
        assert not landed.embarked and landed.used_this_turn
        assert (landed.x, landed.y) == destinations[index]

    class Navigator:
        calls: list[tuple[object, ...]]

        def __init__(self) -> None:
            self.calls = []

        async def select_unit(self, unit_id, observation):
            self.calls.append(("select", unit_id))
            return _game_state_at(
                initial.game_state,
                123,
                battle,
                MenuObservation(123, MenuFamily.UNIT_MOVEMENT, selected_unit=carrier_selected),
            )

        async def move_selected_unit_along_path(self, path, **kwargs):
            self.calls.append(("move", tuple(path)))
            return _game_state_at(initial.game_state, 124, battle, action_menu)

        async def choose_unload(self, point, *, unit, width, height):
            assert (width, height) == (battle.map.width, battle.map.height)
            self.calls.append(("drop", point))
            return after_drop_states[len([call for call in self.calls if call[0] == "drop"]) - 1]

        async def choose_wait(self):
            self.calls.append(("wait",))
            return final_state

    navigator = Navigator()
    request = CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=initial.revision,
        action=UnloadAction(
            transport_id=carrier_id,
            path=(),
            drops=tuple(
                CargoDrop(
                    unit_id=identity_id,
                    destination=Coordinate(x=destination[0], y=destination[1]),
                )
                for identity_id, destination in zip(cargo_ids, destinations, strict=True)
            ),
        ),
    )
    outcome = asyncio.run(
        UnloadActionExecutor(cast(ActionNavigator, navigator), tracker).execute(request, initial)
    )

    expected_calls = [
        ("select", carrier_id),
        ("move", ()),
        *(("drop", destination) for destination in destinations),
    ]
    if carrier_type != 7:
        expected_calls.append(("wait",))
    assert navigator.calls == expected_calls
    assert outcome.observation is not None and outcome.observation.revision == 2
    committed = outcome.observation.game_state.battle.value
    assert committed is not None
    committed_carrier = next(
        unit for unit in committed.units if unit.reference == carrier.reference
    )
    for index, cargo in enumerate(cargoes):
        committed_cargo = next(
            unit for unit in committed.units if unit.reference == cargo.reference
        )
        assert not committed_cargo.embarked and committed_cargo.used_this_turn
        assert (committed_cargo.x, committed_cargo.y) == destinations[index]
    assert committed_carrier.used_this_turn and not committed_carrier.cargo_references


def test_unload_rejects_an_occupied_drop_tile_before_emulator_input(memory) -> None:
    tracker, initial, carrier, _cargoes, carrier_id, cargo_ids, _destinations = _setup(memory)

    class NoInputNavigator:
        async def select_unit(self, *args, **kwargs):
            pytest.fail("occupied-drop validation must happen before emulator input")

    request = CommandRequest(
        match_id=initial.match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=initial.revision,
        action=UnloadAction(
            transport_id=carrier_id,
            path=(),
            drops=(
                CargoDrop(
                    unit_id=cargo_ids[0],
                    destination=Coordinate(x=carrier.x, y=carrier.y),
                ),
            ),
        ),
    )
    with pytest.raises(CommandRejected, match="occupied"):
        asyncio.run(
            UnloadActionExecutor(cast(ActionNavigator, NoInputNavigator()), tracker).execute(
                request, initial
            )
        )
