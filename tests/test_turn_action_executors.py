"""ROM-independent checks for end-turn and surrender outcomes."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast
from uuid import uuid4

from pydantic import SecretStr
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.end_turn_executor import EndTurnActionExecutor
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    EndTurnAction,
    MatchLifecycle,
    PlayerSlot,
    SurrenderAction,
)
from aw2_lab.match_observation import IdentityStatus, MatchObservationTracker
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import ObservedValue, ValueStatus
from aw2_lab.surrender_executor import SurrenderActionExecutor
from aw2_lab.ui_state import MenuFamily, MenuItem, MenuObservation


def _request(match_id, action) -> CommandRequest:
    return CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=1,
        action=action,
    )


def _map_boundary(state, frame: int, battle):
    return replace(
        state,
        frame=frame,
        validation=replace(state.validation, frame=frame),
        ui=replace(
            state.ui,
            frame=frame,
            map_cursor=replace(state.ui.map_cursor, frame=frame),
            menu=MenuObservation(frame, MenuFamily.MAP_INPUT),
        ),
        battle=replace(state.battle, value=battle),
    )


def test_end_turn_verifies_next_player_and_new_day(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    battle = initial.game_state.battle.value
    assert battle is not None
    next_slot = 2 if battle.active_player_slot == 1 else 1
    next_day = battle.day + (1 if battle.active_player_slot == 2 else 0)
    next_battle = replace(
        battle,
        active_player_slot=next_slot,
        day=next_day,
        units=tuple(
            replace(unit, used_this_turn=False) if unit.army_slot == next_slot else unit
            for unit in battle.units
        ),
    )
    final_state = _map_boundary(initial.game_state, initial.game_state.frame + 1, next_battle)

    class FakeNavigator:
        calls: list[object]

        def __init__(self) -> None:
            self.calls = []

        async def open_command_menu(self):
            self.calls.append("open")

        async def navigate_menu(self, item):
            self.calls.append(("navigate", item))

        async def confirm_end_turn(self):
            self.calls.append("confirm")
            return final_state

    navigator = FakeNavigator()
    outcome = asyncio.run(
        EndTurnActionExecutor(cast(ActionNavigator, navigator), tracker).execute(
            _request(tracker.match_id, EndTurnAction()), initial
        )
    )

    assert navigator.calls == ["open", ("navigate", MenuItem.END), "confirm"]
    assert outcome.lifecycle is MatchLifecycle.PLAYABLE
    assert outcome.observation is not None
    result = outcome.observation.game_state.battle.value
    assert result is not None
    assert (result.active_player_slot, result.day) == (next_slot, next_day)


def test_surrender_commits_terminal_result_without_live_battle(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    result_phase = replace(
        initial.game_state.validation.lifecycle,
        phase=LifecyclePhase.DEFEAT_PRESENTATION,
    )
    result_state = replace(
        initial.game_state,
        frame=initial.game_state.frame + 1,
        validation=replace(
            initial.game_state.validation,
            frame=initial.game_state.frame + 1,
            lifecycle=result_phase,
        ),
        ui=replace(
            initial.game_state.ui,
            frame=initial.game_state.frame + 1,
            map_cursor=replace(
                initial.game_state.ui.map_cursor, frame=initial.game_state.frame + 1
            ),
            menu=MenuObservation(initial.game_state.frame + 1, MenuFamily.UNRESOLVED),
        ),
        battle=ObservedValue(ValueStatus.UNAVAILABLE, None, ("Terminal result phase",)),
    )

    class FakeNavigator:
        calls: list[object]

        def __init__(self) -> None:
            self.calls = []

        async def open_command_menu(self):
            self.calls.append("open")

        async def navigate_menu(self, item):
            self.calls.append(("navigate", item))

        async def open_yield_confirmation(self):
            self.calls.append("yield")

        async def confirm_yield(self):
            self.calls.append("yes")
            return result_state

    navigator = FakeNavigator()
    outcome = asyncio.run(
        SurrenderActionExecutor(cast(ActionNavigator, navigator), tracker).execute(
            _request(tracker.match_id, SurrenderAction()), initial
        )
    )

    assert navigator.calls == ["open", ("navigate", MenuItem.YIELD), "yield", "yes"]
    assert outcome.lifecycle is MatchLifecycle.FINISHED
    assert outcome.observation is not None
    assert outcome.observation.identity_status is IdentityStatus.UNAVAILABLE
    assert outcome.observation.game_state.battle.status is ValueStatus.UNAVAILABLE
