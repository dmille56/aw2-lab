"""ROM-independent orchestration checks for Move and Attack."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from struct import pack_into
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
    MoveAttackAction,
    PlayerSlot,
)
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservation, MatchObservationTracker
from aw2_lab.move_attack_executor import MoveAttackActionExecutor
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import GameState
from aw2_lab.ui_state import MenuFamily, MenuObservation, SelectedUnitObservation


def request(
    match_id: UUID,
    unit_id: str,
    *,
    path: tuple[tuple[int, int], ...] = (),
    target: tuple[int, int] = (1, 1),
) -> CommandRequest:
    return CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=1,
        action=MoveAttackAction(
            unit_id=unit_id,
            path=tuple(Coordinate(x=x, y=y) for x, y in path),
            target=Coordinate(x=target[0], y=target[1]),
        ),
    )


def test_move_attack_executes_targeting_and_commits_verified_result(memory) -> None:
    match_id = uuid4()
    tracker = MatchObservationTracker(match_id)
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    battle = initial.game_state.battle.value
    assert battle is not None
    attacker = next(unit for unit in battle.units if unit.army_slot == battle.active_player_slot)
    target = next(unit for unit in battle.units if unit.army_slot != battle.active_player_slot)
    unit_id = next(
        item.identity_id for item in initial.unit_identities if item.reference == attacker.reference
    )
    selected = SelectedUnitObservation(
        0x02022684 + attacker.reference * 12,
        attacker.army_slot,
        attacker.unit_slot,
        attacker.unit_type,
        attacker.x,
        attacker.y,
    )
    final_units = tuple(
        replace(unit, used_this_turn=True)
        if unit.reference == attacker.reference
        else replace(unit, internal_health=unit.internal_health - 1)
        if unit.reference == target.reference
        else unit
        for unit in battle.units
    )
    final_battle = replace(battle, units=final_units)
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

        async def select_unit(self, unit_id: str, observation: MatchObservation) -> GameState:
            self.calls.append(("select", unit_id))
            return replace(
                initial.game_state,
                ui=replace(
                    initial.game_state.ui,
                    menu=MenuObservation(123, MenuFamily.UNIT_MOVEMENT, selected),
                ),
            )

        async def move_selected_unit_along_path(self, path, **kwargs) -> None:
            self.calls.append(("move", tuple(path)))

        async def choose_fire(self):
            self.calls.append(("fire",))

        async def move_target_cursor_to(self, x: int, y: int, **kwargs) -> None:
            self.calls.append(("target", x, y))

        async def confirm_attack(self):
            self.calls.append(("confirm",))
            return final_state

    navigator = FakeNavigator()
    outcome = asyncio.run(
        MoveAttackActionExecutor(cast(ActionNavigator, navigator), tracker).execute(
            request(match_id, unit_id, path=((0, 1),)), initial
        )
    )

    assert navigator.calls == [
        ("select", unit_id),
        ("move", ((0, 1),)),
        ("fire",),
        ("target", 1, 1),
        ("confirm",),
    ]
    assert outcome.lifecycle is MatchLifecycle.PLAYABLE
    assert outcome.observation is not None
    assert outcome.observation.revision == 2


@pytest.mark.parametrize(
    ("unit_type", "target_type", "path", "message"),
    [
        (10, 1, ((0, 1),), "Indirect units"),
        (5, 16, ((0, 1),), "compatible weapon"),
        (23, 1, ((0, 1),), "no weapons"),
    ],
)
def test_rule_rejection_happens_before_any_controller_input(
    memory,
    unit_type: int,
    target_type: int,
    path: tuple[tuple[int, int], ...],
    message: str,
) -> None:
    _, ewram, _ = memory
    ewram[0x22690] = unit_type
    pack_into("<H", ewram, 0x22694, 100 | (9 << 7))
    ewram[0x22990] = target_type
    tracker = MatchObservationTracker(uuid4())
    initial = tracker.commit_boundary(decode_snapshot(snapshot(memory)))
    identity = next(item.identity_id for item in initial.unit_identities if item.reference == 1)
    # An object without navigator methods makes any attempted input fail this test.
    executor = MoveAttackActionExecutor(cast(ActionNavigator, object()), tracker)
    with pytest.raises(CommandRejected, match=message):
        asyncio.run(executor.execute(request(initial.match_id, identity, path=path), initial))
