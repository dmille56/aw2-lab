"""ROM-independent pre-input guards for silo launch commands."""

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
from aw2_lab.match_contract import (
    CommandRequest,
    Coordinate,
    PlayerSlot,
    SiloLaunchAction,
)
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.silo_executor import SiloLaunchActionExecutor
from aw2_lab.state_decoder import decode_snapshot


@pytest.mark.parametrize("unused_silo", [False, True])
def test_silo_executor_rejects_invalid_target_before_input(memory, unused_silo: bool) -> None:
    tracker = MatchObservationTracker(uuid4())
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    if unused_silo:
        tiles = tuple(
            replace(tile, terrain_class=17) if (tile.x, tile.y) == (0, 0) else tile
            for tile in battle.map.tiles
        )
        state = replace(
            state,
            battle=replace(
                state.battle, value=replace(battle, map=replace(battle.map, tiles=tiles))
            ),
        )
        battle = state.battle.value
        assert battle is not None
    source = battle.units[0]
    observation = tracker.commit_boundary(state)
    unit_id = next(
        item.identity_id
        for item in observation.unit_identities
        if item.reference == source.reference
    )
    request = CommandRequest(
        match_id=observation.match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=observation.revision,
        action=SiloLaunchAction(
            unit_id=unit_id,
            path=(),
            target=Coordinate(x=2, y=0) if unused_silo else Coordinate(x=1, y=1),
        ),
    )
    executor = SiloLaunchActionExecutor(cast(ActionNavigator, None), tracker)

    expected = "outside the map" if unused_silo else "unused missile silo"
    with pytest.raises(CommandRejected, match=expected):
        asyncio.run(executor.execute(request, observation))
