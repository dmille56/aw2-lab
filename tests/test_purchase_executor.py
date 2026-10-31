"""ROM-independent checks for purchase preflight and verified outcomes."""

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
from aw2_lab.match_contract import CommandRequest, Coordinate, PlayerSlot, PurchaseAction
from aw2_lab.match_controller import CommandRejected
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.purchase_executor import PurchaseActionExecutor
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import PropertyState
from aw2_lab.ui_state import MenuFamily, MenuObservation


def _request(match_id: UUID, unit_type: str = "Infantry") -> CommandRequest:
    return CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr("x" * 32),
        request_id=uuid4(),
        expected_revision=1,
        action=PurchaseAction(
            property=Coordinate(x=1, y=0),
            unit_type=unit_type,
        ),
    )


def _base_observation(memory):
    tracker = MatchObservationTracker(uuid4())
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    player = next(item for item in battle.players if item.slot == battle.active_player_slot)
    state = replace(
        state,
        battle=replace(
            state.battle,
            value=replace(
                battle,
                players=tuple(
                    replace(item, funds=10_000) if item.slot == player.slot else item
                    for item in battle.players
                ),
                properties=(PropertyState(1, 0, terrain_class=14, owner_slot=player.slot),),
            ),
        ),
    )
    return tracker, tracker.commit_boundary(state)


def test_purchase_executes_and_verifies_new_unit(memory) -> None:
    tracker, initial = _base_observation(memory)
    battle = initial.game_state.battle.value
    assert battle is not None
    player = next(item for item in battle.players if item.slot == battle.active_player_slot)
    template = battle.units[0]
    new_unit = replace(
        template,
        reference=max(item.reference for item in battle.units) + 1,
        unit_slot=3,
        unit_type=1,
        x=1,
        y=0,
        used_this_turn=True,
        embarked=False,
    )
    final_battle = replace(
        battle,
        units=battle.units + (new_unit,),
        players=tuple(
            replace(item, funds=player.funds - 1000)
            if item.slot == battle.active_player_slot
            else item
            for item in battle.players
        ),
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

        async def open_production_menu(self, x, y):
            self.calls.append(("open", x, y))
            return initial.game_state

        async def choose_purchase_unit(self, unit_type):
            self.calls.append(("choose", unit_type))
            return final_state

    navigator = FakeNavigator()
    outcome = asyncio.run(
        PurchaseActionExecutor(cast(ActionNavigator, navigator), tracker).execute(
            _request(tracker.match_id), initial
        )
    )

    assert navigator.calls == [("open", 1, 0), ("choose", 1)]
    assert outcome.observation is not None
    assert outcome.observation.revision == 2
    assert len(outcome.observation.unit_identities) == len(battle.units) + 1


@pytest.mark.parametrize(
    ("unit_type", "property_state", "funds", "occupied", "message"),
    [
        ("Fighter", "base", 10_000, False, "not available"),
        ("Infantry", "unowned", 10_000, False, "not owned"),
        ("Infantry", "base", 500, False, "Insufficient funds"),
        ("Infantry", "base", 10_000, True, "occupied"),
        ("Infantry", "city", 10_000, False, "supports researched base"),
    ],
)
def test_purchase_rejects_before_input(
    memory, unit_type, property_state, funds, occupied, message
) -> None:
    tracker, initial = _base_observation(memory)
    battle = initial.game_state.battle.value
    assert battle is not None
    player = next(item for item in battle.players if item.slot == battle.active_player_slot)
    terrain, owner = {
        "base": (14, player.slot),
        "unowned": (14, 0),
        "city": (6, player.slot),
    }[property_state]
    units = battle.units
    if occupied:
        units = units + (
            replace(units[0], reference=max(u.reference for u in units) + 1, x=1, y=0),
        )
    prepared = replace(
        initial.game_state,
        frame=124,
        validation=replace(initial.game_state.validation, frame=124),
        ui=replace(
            initial.game_state.ui,
            frame=124,
            map_cursor=replace(initial.game_state.ui.map_cursor, frame=124),
            menu=MenuObservation(124, MenuFamily.MAP_INPUT),
        ),
        battle=replace(
            initial.game_state.battle,
            value=replace(
                battle,
                units=units,
                players=tuple(
                    replace(item, funds=funds) if item.slot == player.slot else item
                    for item in battle.players
                ),
                properties=(PropertyState(1, 0, terrain, owner),),
            ),
        ),
    )
    initial = tracker.commit_boundary(prepared)

    class NoInputNavigator:
        async def open_production_menu(self, *args, **kwargs):
            pytest.fail("purchase preflight rejection must happen before emulator input")

    with pytest.raises(CommandRejected, match=message):
        asyncio.run(
            PurchaseActionExecutor(cast(ActionNavigator, NoInputNavigator()), tracker).execute(
                _request(tracker.match_id, unit_type), initial
            )
        )
