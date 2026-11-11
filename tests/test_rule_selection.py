"""Rules-screen selector navigation checks every accepted input in RAM."""

import asyncio
from dataclasses import replace

import pytest

from aw2_lab.cold_boot import (
    _KEY_DOWN,
    _KEY_UP,
    _WEATHER_SELECTOR_INDEX,
    _FrontendState,
    _select_rule_value,
    _verify_rules,
)
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import MatchRules, StartingWeather


def rules_state(**changes: int) -> _FrontendState:
    state = _FrontendState(
        frame=0,
        phase=LifecyclePhase.VERSUS_SETUP,
        map_id=1,
        setup_subphase=2,
        setup=b"",
        setup_focus=0,
        selector_object=0,
        selector_table=0,
        yes_no_selection=0,
        fog_rule=1,
        weather_rule=1,
        income_rule=0,
        day_rule=26,
        capture_rule=0,
        powers_rule=0,
    )
    return replace(state, **changes)


def test_rules_verifier_matches_selected_values():
    rules = MatchRules(
        starting_funds=3000,
        day_limit=None,
        capture_limit=20,
        co_powers=False,
    )
    _verify_rules(rules_state(income_rule=4, day_rule=0, capture_rule=9, powers_rule=1), rules)


@pytest.mark.parametrize("weather", ("random", "clear", "rain", "snow"))
def test_weather_selector_indexes_match_the_advertised_choices(weather: StartingWeather):
    rules = MatchRules(starting_weather=weather)
    _verify_rules(
        rules_state(weather_rule=_WEATHER_SELECTOR_INDEX[weather]),
        rules,
    )


@pytest.mark.parametrize(
    ("field", "current", "target", "maximum"),
    [
        ("income_rule", 0, 8, 8),
        ("day_rule", 26, 0, 95),
        ("capture_rule", 0, 16, 16),
        ("powers_rule", 0, 1, 1),
    ],
)
def test_rule_selector_checks_each_step(field: str, current: int, target: int, maximum: int):
    initial = rules_state(**{field: current})
    current_state = [initial]

    async def tap(_label: str, keys: int) -> _FrontendState:
        state = current_state[0]
        delta = 1 if keys == _KEY_DOWN else -1 if keys == _KEY_UP else 0
        state = replace(state, frame=state.frame + 1, **{field: getattr(state, field) + delta})
        current_state[0] = state
        return state

    async def settle() -> _FrontendState:
        return current_state[0]

    result = asyncio.run(_select_rule_value(initial, tap, settle, field, target, maximum, field))
    assert getattr(result, field) == target
