"""ROM-independent executor checks for the Join action."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.join_executor import JoinActionExecutor
from aw2_lab.match_contract import (
    CommandRequest,
    Coordinate,
    JoinAction,
    MatchLifecycle,
    PlayerSlot,
)
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.ui_state import MenuFamily, MenuObservation, SelectedUnitObservation


def _request(match_id: UUID, unit_id: str, point: tuple[int, int]) -> CommandRequest:
    return CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=1,
        action=JoinAction(
            unit_id=unit_id,
            path=(Coordinate(x=point[0], y=point[1]),),
        ),
    )


def test_join_moves_onto_partner_and_verifies_moving_unit_survives(memory) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    source = next(unit for unit in battle.units if unit.army_slot == battle.active_player_slot)
    source = replace(source, internal_health=27)
    battle = replace(
        battle,
        units=tuple(
            source if unit.reference == source.reference else unit for unit in battle.units
        ),
    )
    destination = (source.x + 1, source.y)
    partner = replace(
        source,
        reference=2,
        unit_slot=2,
        x=destination[0],
        y=destination[1],
        internal_health=51,
    )
    initial_state = replace(
        state,
        battle=replace(state.battle, value=replace(battle, units=(*battle.units, partner))),
    )
    initial = tracker.commit_boundary(initial_state)
    source_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == source.reference
    )

    selected = SelectedUnitObservation(
        0x02022684 + source.reference * 12,
        source.army_slot,
        source.unit_slot,
        source.unit_type,
        source.x,
        source.y,
    )
    final_source = replace(
        source,
        x=destination[0],
        y=destination[1],
        internal_health=90,
        used_this_turn=True,
    )
    final_battle = replace(battle, units=(final_source,))
    final_state = replace(
        initial_state,
        frame=124,
        validation=replace(initial_state.validation, frame=124),
        ui=replace(
            initial_state.ui,
            frame=124,
            map_cursor=replace(initial_state.ui.map_cursor, frame=124),
            menu=MenuObservation(124, MenuFamily.MAP_INPUT),
        ),
        battle=replace(initial_state.battle, value=final_battle),
    )

    class FakeNavigator:
        calls: list[tuple[object, ...]]

        def __init__(self) -> None:
            self.calls = []

        async def select_unit(self, requested_id, observation):
            self.calls.append(("select", requested_id))
            return replace(
                initial_state,
                ui=replace(
                    initial_state.ui,
                    menu=MenuObservation(123, MenuFamily.UNIT_MOVEMENT, selected),
                ),
            )

        async def move_selected_unit_along_path(self, path, **kwargs):
            self.calls.append(("move", tuple(path)))

        async def choose_join(self):
            self.calls.append(("join",))
            return final_state

    navigator = FakeNavigator()
    request = _request(match_id, source_id, destination)
    outcome = asyncio.run(
        JoinActionExecutor(cast(ActionNavigator, navigator), tracker).execute(request, initial)
    )
    assert navigator.calls == [("select", source_id), ("move", (destination,)), ("join",)]
    assert outcome.lifecycle is MatchLifecycle.PLAYABLE
    assert outcome.observation is not None
    assert outcome.observation.revision == 2
    assert [unit.reference for unit in outcome.observation.game_state.battle.value.units] == [
        source.reference
    ]


@pytest.mark.parametrize(("partner_type", "used"), [(2, False), (1, True)])
def test_join_rejects_wrong_type_or_used_partner_before_input(memory, partner_type, used) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    source = next(unit for unit in battle.units if unit.army_slot == battle.active_player_slot)
    destination = (source.x + 1, source.y)
    partner = replace(
        source,
        reference=2,
        unit_slot=2,
        unit_type=partner_type,
        x=destination[0],
        y=destination[1],
        used_this_turn=used,
    )
    battle = replace(battle, units=(*battle.units, partner))
    initial = tracker.commit_boundary(replace(state, battle=replace(state.battle, value=battle)))
    source_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == source.reference
    )

    class NoInputNavigator:
        async def select_unit(self, *args, **kwargs):
            pytest.fail("invalid Join partner must be rejected before input")

    with pytest.raises(CommandRejected, match="same type"):
        asyncio.run(
            JoinActionExecutor(cast(ActionNavigator, NoInputNavigator()), tracker).execute(
                _request(match_id, source_id, destination), initial
            )
        )
