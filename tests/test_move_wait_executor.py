"""ROM-independent orchestration checks for Move and Wait."""

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
from aw2_lab.match_contract import CommandRequest, Coordinate, MoveWaitAction, PlayerSlot
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.move_wait_executor import MoveWaitActionExecutor
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import GameState
from aw2_lab.ui_state import MenuFamily, MenuObservation, SelectedUnitObservation


def _request(match_id: UUID, unit_id: str, path: tuple[tuple[int, int], ...]) -> CommandRequest:
    return CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=1,
        action=MoveWaitAction(
            unit_id=unit_id,
            path=tuple(Coordinate(x=x, y=y) for x, y in path),
        ),
    )


@pytest.mark.parametrize(
    ("path", "reached"),
    [
        ((), (0, 0)),
        (((1, 0),), (1, 0)),
        (((1, 0), (1, 1)), (1, 0)),
    ],
    ids=("stationary", "move", "fog-hidden-blocker"),
)
def test_move_wait_commits_actual_reached_tile(memory, path, reached) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
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
    moved_unit = replace(unit, x=reached[0], y=reached[1])
    movement_battle = replace(
        battle,
        units=tuple(
            moved_unit if item.reference == unit.reference else item for item in battle.units
        ),
    )
    final_unit = replace(moved_unit, used_this_turn=True)
    final_battle = replace(
        movement_battle,
        units=tuple(
            final_unit if item.reference == unit.reference else item for item in battle.units
        ),
    )

    def state_at(frame: int, game_battle) -> GameState:
        return replace(
            initial.game_state,
            frame=frame,
            validation=replace(initial.game_state.validation, frame=frame),
            ui=replace(
                initial.game_state.ui,
                frame=frame,
                map_cursor=replace(initial.game_state.ui.map_cursor, frame=frame),
                menu=MenuObservation(frame, MenuFamily.MAP_INPUT),
            ),
            battle=replace(initial.game_state.battle, value=game_battle),
        )

    movement_state = replace(
        state_at(124, movement_battle),
        ui=replace(
            state_at(124, movement_battle).ui,
            menu=MenuObservation(
                124, MenuFamily.UNIT_ACTION_CHOICES, selected_unit=selected, actionable=True
            ),
        ),
    )
    final_state = state_at(125, final_battle)

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

        async def move_selected_unit_along_path(self, requested_path, **kwargs):
            self.calls.append(("move", tuple(requested_path)))
            return movement_state

        async def choose_wait(self):
            self.calls.append(("wait",))
            return final_state

    navigator = FakeNavigator()
    outcome = asyncio.run(
        MoveWaitActionExecutor(cast(ActionNavigator, navigator), tracker).execute(
            _request(match_id, unit_id, path), initial
        )
    )

    assert navigator.calls == [("select", unit_id), ("move", path), ("wait",)]
    assert outcome.observation is not None
    assert outcome.observation.revision == 2
    result_battle = outcome.observation.game_state.battle.value
    assert result_battle is not None
    result_unit = next(item for item in result_battle.units if item.reference == unit.reference)
    assert (result_unit.x, result_unit.y) == reached
    assert result_unit.used_this_turn


def test_move_wait_rejects_invalid_route_before_input(memory) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    unit = initial.game_state.battle.value.units[0]
    unit_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == unit.reference
    )

    class NoInputNavigator:
        async def select_unit(self, *args, **kwargs):
            pytest.fail("preflight rejection must happen before emulator input")

    with pytest.raises(CommandRejected, match="outside the map"):
        asyncio.run(
            MoveWaitActionExecutor(cast(ActionNavigator, NoInputNavigator()), tracker).execute(
                _request(match_id, unit_id, ((2, 0),)), initial
            )
        )


def test_move_wait_rejects_unavailable_unit_before_input(memory) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))

    class NoInputNavigator:
        async def select_unit(self, *args, **kwargs):
            pytest.fail("preflight rejection must happen before emulator input")

    with pytest.raises(CommandRejected, match="unavailable"):
        asyncio.run(
            MoveWaitActionExecutor(cast(ActionNavigator, NoInputNavigator()), tracker).execute(
                _request(match_id, "missing-unit", ()), initial
            )
        )


def test_move_wait_rejects_post_movement_position_outside_route(memory) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    unit = initial.game_state.battle.value.units[0]
    unit_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == unit.reference
    )
    selected = SelectedUnitObservation(
        0x02022684 + unit.reference * 12,
        unit.army_slot,
        unit.unit_slot,
        unit.unit_type,
        1,
        1,
    )
    movement_state = replace(
        initial.game_state,
        ui=replace(
            initial.game_state.ui,
            menu=MenuObservation(
                initial.game_state.frame,
                MenuFamily.UNIT_ACTION_CHOICES,
                selected_unit=selected,
                actionable=True,
            ),
        ),
    )
    final_battle = replace(
        initial.game_state.battle.value,
        units=tuple(
            replace(item, x=1, y=1, used_this_turn=True)
            if item.reference == unit.reference
            else item
            for item in initial.game_state.battle.value.units
        ),
    )
    final_state = replace(
        initial.game_state,
        frame=initial.game_state.frame + 1,
        validation=replace(initial.game_state.validation, frame=initial.game_state.frame + 1),
        ui=replace(
            initial.game_state.ui,
            frame=initial.game_state.frame + 1,
            map_cursor=replace(
                initial.game_state.ui.map_cursor, frame=initial.game_state.frame + 1
            ),
            menu=MenuObservation(
                initial.game_state.frame + 1,
                MenuFamily.MAP_INPUT,
            ),
        ),
        battle=replace(initial.game_state.battle, value=final_battle),
    )

    class Navigator:
        async def select_unit(self, *args, **kwargs):
            return replace(
                initial.game_state,
                ui=replace(
                    initial.game_state.ui,
                    menu=MenuObservation(
                        initial.game_state.frame, MenuFamily.UNIT_MOVEMENT, selected
                    ),
                ),
            )

        async def move_selected_unit_along_path(self, *args, **kwargs):
            return movement_state

        async def choose_wait(self):
            return final_state

    with pytest.raises(RuntimeError, match="outside the requested route"):
        asyncio.run(
            MoveWaitActionExecutor(cast(ActionNavigator, Navigator()), tracker).execute(
                _request(match_id, unit_id, ((1, 0),)), initial
            )
        )
