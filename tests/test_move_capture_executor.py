"""ROM-independent orchestration checks for Move and Capture."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.match_contract import (
    CommandRequest,
    Coordinate,
    MatchLifecycle,
    MoveCaptureAction,
    PlayerSlot,
)
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.move_capture_executor import MoveCaptureActionExecutor
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import PropertyState
from aw2_lab.ui_state import MenuFamily, MenuObservation, SelectedUnitObservation


def _request(match_id: UUID, unit_id: str, path: tuple[tuple[int, int], ...]) -> CommandRequest:
    return CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=1,
        action=MoveCaptureAction(
            unit_id=unit_id,
            path=tuple(Coordinate(x=x, y=y) for x, y in path),
        ),
    )


@pytest.mark.parametrize(
    ("path", "destination", "owner", "points"),
    [
        ((), (0, 0), 0, 10),
        (((1, 0),), (1, 0), 0, 10),
        ((), (0, 0), 1, 0),
    ],
    ids=("stationary-progress", "move-progress", "capture-completes"),
)
def test_move_capture_executes_and_verifies_outcome(
    memory, path, destination, owner, points
) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial_state = decode_snapshot(snapshot(memory))
    initial_battle = initial_state.battle.value
    assert initial_battle is not None
    initial_state = replace(
        initial_state,
        battle=replace(
            initial_state.battle,
            value=replace(
                initial_battle,
                properties=(PropertyState(*destination, terrain_class=6, owner_slot=0),),
            ),
        ),
    )
    initial = tracker.commit_boundary(initial_state)
    battle = initial.game_state.battle.value
    assert battle is not None
    unit = next(item for item in battle.units if item.army_slot == battle.active_player_slot)
    unit_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == unit.reference
    )
    selected = SelectedUnitObservation(
        0x02022684 + unit.reference * 12,
        unit.army_slot,
        unit.unit_slot,
        unit.unit_type,
        unit.x,
        unit.y,
    )
    final_unit = replace(
        unit,
        x=destination[0],
        y=destination[1],
        used_this_turn=True,
        capture_points=points,
    )
    final_battle = replace(
        battle,
        units=tuple(
            final_unit if item.reference == unit.reference else item for item in battle.units
        ),
        properties=(PropertyState(*destination, terrain_class=6, owner_slot=owner),),
    )
    final_state = replace(
        initial.game_state,
        frame=124,
        validation=replace(initial.game_state.validation, frame=124),
        ui=replace(
            initial.game_state.ui,
            frame=124,
            map_cursor=replace(initial.game_state.ui.map_cursor, frame=124),
            menu=MenuObservation(124, MenuFamily.MAP_INPUT),
        ),
        battle=replace(initial.game_state.battle, value=final_battle),
    )

    class FakeNavigator:
        calls: list[tuple[object, ...]]

        def __init__(self) -> None:
            self.calls = []

        async def select_unit(self, requested_id, observation):
            self.calls.append(("select", requested_id))
            return replace(
                initial.game_state,
                ui=replace(
                    initial.game_state.ui,
                    menu=MenuObservation(123, MenuFamily.UNIT_MOVEMENT, selected),
                ),
            )

        async def move_selected_unit_along_path(self, requested_path, **kwargs) -> None:
            self.calls.append(("move", tuple(requested_path)))

        async def choose_capture(self):
            self.calls.append(("capture",))
            return final_state

    navigator = FakeNavigator()
    outcome = asyncio.run(
        MoveCaptureActionExecutor(cast(ActionNavigator, navigator), tracker).execute(
            _request(match_id, unit_id, path), initial
        )
    )

    assert navigator.calls == [("select", unit_id), ("move", path), ("capture",)]
    assert outcome.lifecycle is MatchLifecycle.PLAYABLE
    assert outcome.observation is not None
    assert outcome.observation.revision == 2
    committed_unit = next(
        item
        for item in outcome.observation.game_state.battle.value.units
        if item.reference == unit.reference
    )
    assert committed_unit.capture_points == points


def test_move_capture_rejects_non_property_before_emulator_input(memory) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    battle = initial.game_state.battle.value
    assert battle is not None
    unit = next(item for item in battle.units if item.army_slot == battle.active_player_slot)
    unit_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == unit.reference
    )

    class NoInputNavigator:
        async def select_unit(self, *args, **kwargs):
            pytest.fail("preflight rejection must happen before emulator input")

    with pytest.raises(CommandRejected, match="capturable property"):
        asyncio.run(
            MoveCaptureActionExecutor(cast(ActionNavigator, NoInputNavigator()), tracker).execute(
                _request(match_id, unit_id, ((1, 0),)), initial
            )
        )
