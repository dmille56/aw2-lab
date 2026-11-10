"""ROM-independent input guards for Sub Dive and Rise."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.match_contract import CommandRequest, DiveAction, PlayerSlot, RiseAction
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.submarine_executor import DiveActionExecutor, RiseActionExecutor


@pytest.mark.parametrize(
    ("action_kind", "initial_submerged", "executor_type"),
    [
        ("dive", True, DiveActionExecutor),
        ("rise", False, RiseActionExecutor),
    ],
)
def test_submarine_executor_rejects_wrong_surface_mode_before_input(
    memory, action_kind, initial_submerged, executor_type
) -> None:
    tracker = MatchObservationTracker(uuid4())
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    source = battle.units[0]
    sub = replace(source, unit_type=24, submerged=initial_submerged, used_this_turn=False)
    state = replace(
        state,
        battle=replace(
            state.battle,
            value=replace(
                battle,
                units=tuple(
                    sub if unit.reference == source.reference else unit for unit in battle.units
                ),
            ),
        ),
    )
    observation = tracker.commit_boundary(state)
    unit_id = next(
        item.identity_id for item in observation.unit_identities if item.reference == sub.reference
    )
    action = (
        DiveAction(unit_id=unit_id, path=())
        if action_kind == "dive"
        else RiseAction(unit_id=unit_id, path=())
    )
    request = CommandRequest(
        match_id=observation.match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=observation.revision,
        action=action,
    )
    executor = executor_type(cast(ActionNavigator, None), tracker)

    with pytest.raises(CommandRejected, match="surfaced|submerged"):
        asyncio.run(executor.execute(request, observation))
