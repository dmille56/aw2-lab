"""CO setup navigation is bounded and checks each accepted menu input."""

import asyncio
from dataclasses import replace

import pytest

from aw2_lab.cold_boot import (
    _CO_SETUP_INDEX,
    _KEY_DOWN,
    _KEY_UP,
    _FrontendState,
    _select_setup_co,
)
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CO_ID_VALUES


def setup_state(slot: int, current: int) -> _FrontendState:
    setup = bytearray(0x30)
    setup[:2] = bytes((0, 1))
    setup[0x0B:0x0D] = bytes((1, 2))
    setup[0x0B + slot - 1] = current
    return _FrontendState(
        frame=0,
        phase=LifecyclePhase.VERSUS_SETUP,
        map_id=1,
        setup_subphase=0,
        setup=bytes(setup),
        setup_focus=0 if slot == 1 else 2,
        selector_object=0,
        selector_table=0,
        yes_no_selection=0,
        fog_rule=0,
        weather_rule=0,
        income_rule=0,
        day_rule=0,
        capture_rule=0,
        powers_rule=0,
    )


async def assert_selection(slot: int, current: int, co_id: str) -> None:
    initial = setup_state(slot, current)
    state_holder = [initial]

    async def tap(_label: str, keys: int) -> _FrontendState:
        state = state_holder[0]
        setup = bytearray(state.setup)
        delta = 1 if keys == _KEY_DOWN else -1 if keys == _KEY_UP else 0
        offset = 0x0B + slot - 1
        setup[offset] = (setup[offset] + delta) % 19
        state_holder[0] = replace(state, frame=state.frame + 1, setup=bytes(setup))
        return state_holder[0]

    async def settle() -> _FrontendState:
        return state_holder[0]

    result = await _select_setup_co(initial, tap, settle, slot=slot, co_id=co_id)
    assert result.setup[0x0B + slot - 1] == _CO_SETUP_INDEX[co_id]


@pytest.mark.parametrize("slot", (1, 2))
def test_selector_reaches_every_co_and_verifies_steps(slot: int) -> None:
    async def run() -> None:
        for current in range(19):
            for co_id in CO_ID_VALUES:
                await assert_selection(slot, current, co_id)

    asyncio.run(run())
