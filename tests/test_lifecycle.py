"""Lifecycle regressions distilled from observed signals, without game artifacts."""

from dataclasses import replace

import pytest

from aw2_lab.lifecycle import (
    ANIMATION_CALLBACKS,
    BATTLE_CALLBACKS,
    SCREEN_CALLBACKS,
    BattleControlObservation,
    BattleDecodeSafety,
    LifecyclePhase,
    classify_lifecycle,
)

PLAYER_CONTROL = BattleControlObservation(
    mode=1, state=13, lock_count=0, input_gate=0, input_state=0
)


@pytest.mark.parametrize(
    ("state", "lock_count", "phase"),
    [
        (5, 1, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (5, 0, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (9, 1, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (9, 0, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (10, 0, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (12, 0, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (13, 0, LifecyclePhase.BATTLE_PLAYER_TURN),
        (13, 1, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (14, 0, LifecyclePhase.BATTLE_COMPUTER_TURN),
    ],
)
def test_process_free_entry_play_menu_and_ai_observations(
    state: int, lock_count: int, phase: LifecyclePhase
) -> None:
    # Entry gaps ignored a Right pulse, state 13 accepted it, the command menu
    # locked state 13, and the computer turn used state 14.
    result = classify_lifecycle(
        *BATTLE_CALLBACKS,
        [],
        battle_control=replace(PLAYER_CONTROL, state=state, lock_count=lock_count),
    )
    assert result.phase is phase
    assert result.battle_decode_safety is (
        BattleDecodeSafety.BLOCKED
        if phase is LifecyclePhase.BATTLE_COMPUTER_TURN
        else BattleDecodeSafety.UNKNOWN
    )


@pytest.mark.parametrize(
    ("callbacks", "scripts", "phase"),
    [
        (SCREEN_CALLBACKS, [0x08616C54, 0x0849ECE0], LifecyclePhase.VERSUS_MAP_SELECT),
        (SCREEN_CALLBACKS, [0x0849ECE0], LifecyclePhase.VERSUS_SETUP),
        (SCREEN_CALLBACKS, [0x0849E750], LifecyclePhase.BATTLE_TRANSITION),
        (BATTLE_CALLBACKS, [0x08499E18] * 3, LifecyclePhase.BATTLE_TRANSITION),
        (BATTLE_CALLBACKS, [0x0849E750], LifecyclePhase.BATTLE_TRANSITION),
        (BATTLE_CALLBACKS, [0x0849D56C, 0x084C327C], LifecyclePhase.DEFEAT_PRESENTATION),
        (SCREEN_CALLBACKS, [0x08615CB0, 0x08615DD8], LifecyclePhase.VICTORY_PRESENTATION),
        (
            BATTLE_CALLBACKS,
            [0x08615CB0, 0x0849E750, 0x0849D56C],
            LifecyclePhase.VICTORY_PRESENTATION,
        ),
        (SCREEN_CALLBACKS, [0x0849D56C, 0x08615FB4], LifecyclePhase.RESULT_SUMMARY),
        (SCREEN_CALLBACKS, [0x0849F330], LifecyclePhase.SAVE_PROGRESS_PROMPT),
    ],
)
def test_known_screens_override_retained_player_control(
    callbacks: tuple[int, int], scripts: list[int], phase: LifecyclePhase
) -> None:
    result = classify_lifecycle(*callbacks, scripts, battle_control=PLAYER_CONTROL)
    assert result.phase is phase
    assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED


@pytest.mark.parametrize(
    "control",
    [
        None,
        replace(PLAYER_CONTROL, mode=0),
        replace(PLAYER_CONTROL, input_gate=1),
        replace(PLAYER_CONTROL, input_gate=-1),
        replace(PLAYER_CONTROL, input_state=4),
    ],
)
def test_incomplete_or_other_control_modes_remain_unresolved(
    control: BattleControlObservation | None,
) -> None:
    result = classify_lifecycle(*BATTLE_CALLBACKS, [], battle_control=control)
    assert result.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
    assert result.battle_decode_safety is BattleDecodeSafety.UNKNOWN


def test_unknown_overlay_prevents_player_turn_recognition() -> None:
    result = classify_lifecycle(*BATTLE_CALLBACKS, [0x0849FD14], battle_control=PLAYER_CONTROL)
    assert result.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED


def test_inactive_slots_do_not_hide_player_turn() -> None:
    result = classify_lifecycle(*BATTLE_CALLBACKS, [0] * 32, battle_control=PLAYER_CONTROL)
    assert result.phase is LifecyclePhase.BATTLE_PLAYER_TURN


def test_unknown_callback_pair_cannot_establish_player_turn() -> None:
    result = classify_lifecycle(0, BATTLE_CALLBACKS[1], [], battle_control=PLAYER_CONTROL)
    assert result.phase is LifecyclePhase.UNKNOWN


def test_conflicting_result_presentations_stay_unknown() -> None:
    result = classify_lifecycle(
        *BATTLE_CALLBACKS, [0x08615CB0, 0x084C327C], battle_control=PLAYER_CONTROL
    )
    assert result.phase is LifecyclePhase.UNKNOWN
    assert result.battle_decode_safety is BattleDecodeSafety.UNKNOWN


@pytest.mark.parametrize("callbacks", [BATTLE_CALLBACKS, ANIMATION_CALLBACKS])
def test_fire_parent_and_resolver_recognize_combat_with_retained_human_state(callbacks) -> None:
    result = classify_lifecycle(
        *callbacks,
        [0x0849A9F8, 0x0849FEF8, 0x0855379C],
        battle_control=PLAYER_CONTROL,
    )
    assert result.phase is LifecyclePhase.BATTLE_COMBAT
    assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED
    assert result.matched_scripts == (0x0849A9F8, 0x0849FEF8)


@pytest.mark.parametrize("scripts", [[], [0x0855379C], [0x0849A9F8], [0x0849FEF8]])
def test_animation_callbacks_alone_do_not_identify_combat_or_player_control(scripts) -> None:
    result = classify_lifecycle(*ANIMATION_CALLBACKS, scripts, battle_control=PLAYER_CONTROL)
    assert result.phase is LifecyclePhase.UNKNOWN
    assert result.battle_decode_safety is BattleDecodeSafety.UNKNOWN


@pytest.mark.parametrize("callbacks", [SCREEN_CALLBACKS, (0, 0)])
def test_combat_scripts_require_a_supported_engine(callbacks) -> None:
    result = classify_lifecycle(*callbacks, [0x0849A9F8, 0x0849FEF8], battle_control=PLAYER_CONTROL)
    assert result.phase is LifecyclePhase.UNKNOWN


@pytest.mark.parametrize("script", [0x08615CB0, 0x084C327C, 0x0849D56C])
def test_results_override_combat_processes(script) -> None:
    result = classify_lifecycle(
        *BATTLE_CALLBACKS, [0x0849A9F8, 0x0849FEF8, script], battle_control=PLAYER_CONTROL
    )
    assert result.phase in {
        LifecyclePhase.VICTORY_PRESENTATION,
        LifecyclePhase.DEFEAT_PRESENTATION,
        LifecyclePhase.RESULT_SEQUENCE,
    }
    assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED


@pytest.mark.parametrize(
    ("state", "lock", "substate", "phase"),
    [
        (16, 0, 4, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (13, 0, 4, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
        (13, 0, 0, LifecyclePhase.BATTLE_PLAYER_TURN),
    ],
)
def test_process_free_combat_cleanup_requires_input_substate_reset(
    state, lock, substate, phase
) -> None:
    # Consecutive destruction checkpoints: frames 19959, 19960, and 19961.
    result = classify_lifecycle(
        *BATTLE_CALLBACKS,
        [],
        battle_control=replace(PLAYER_CONTROL, state=state, lock_count=lock, input_state=substate),
    )
    assert result.phase is phase


@pytest.mark.parametrize("resolver", [0x0849FEF8, 0x0849FFB0])
@pytest.mark.parametrize("callbacks", [BATTLE_CALLBACKS, ANIMATION_CALLBACKS])
def test_computer_combat_does_not_require_a_human_fire_parent(resolver, callbacks) -> None:
    result = classify_lifecycle(
        *callbacks, [resolver], battle_control=replace(PLAYER_CONTROL, state=14, lock_count=1)
    )
    assert result.phase is LifecyclePhase.BATTLE_COMBAT
    assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED
    assert result.matched_scripts == (resolver,)


def test_no_visual_human_combat_uses_the_alternate_resolver() -> None:
    result = classify_lifecycle(
        *BATTLE_CALLBACKS, [0x0849A9F8, 0x0849FFB0], battle_control=PLAYER_CONTROL
    )
    assert result.phase is LifecyclePhase.BATTLE_COMBAT
    assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED


@pytest.mark.parametrize(
    "control", [None, PLAYER_CONTROL, replace(PLAYER_CONTROL, mode=0, state=14)]
)
def test_resolver_without_fire_parent_requires_verified_computer_context(control) -> None:
    result = classify_lifecycle(*BATTLE_CALLBACKS, [0x0849FFB0], battle_control=control)
    assert result.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED


def test_computer_turn_with_unknown_overlay_remains_unresolved() -> None:
    result = classify_lifecycle(
        *BATTLE_CALLBACKS, [0x0849FD14], battle_control=replace(PLAYER_CONTROL, state=14)
    )
    assert result.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED


def test_power_quote_and_effects_are_blocked_despite_human_control_fields() -> None:
    for scripts in ([0x0849D77C], [0x0849D77C, 0x08616794, 0x0849D84C]):
        result = classify_lifecycle(*BATTLE_CALLBACKS, scripts, battle_control=PLAYER_CONTROL)
        assert result.phase is LifecyclePhase.BATTLE_POWER
        assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED
        assert result.matched_scripts == (0x0849D77C,)
    assert (
        classify_lifecycle(*BATTLE_CALLBACKS, [], battle_control=PLAYER_CONTROL).phase
        is LifecyclePhase.BATTLE_PLAYER_TURN
    )


@pytest.mark.parametrize("callbacks", [SCREEN_CALLBACKS, ANIMATION_CALLBACKS, (0, 0)])
def test_power_process_requires_the_verified_battle_callbacks(callbacks) -> None:
    result = classify_lifecycle(*callbacks, [0x0849D77C], battle_control=PLAYER_CONTROL)
    assert result.phase is LifecyclePhase.UNKNOWN


def test_result_presentation_overrides_power_and_computer_combat() -> None:
    result = classify_lifecycle(
        *BATTLE_CALLBACKS,
        [0x0849D77C, 0x0849FEF8, 0x084C327C],
        battle_control=replace(PLAYER_CONTROL, state=14),
    )
    assert result.phase is LifecyclePhase.DEFEAT_PRESENTATION
    assert result.battle_decode_safety is BattleDecodeSafety.BLOCKED
