"""Lifecycle regressions distilled from observed signals, without game artifacts."""

from dataclasses import replace

import pytest

from aw2_lab.lifecycle import (
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
        (14, 0, LifecyclePhase.BATTLE_ENGINE_UNRESOLVED),
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
    assert result.battle_decode_safety is BattleDecodeSafety.UNKNOWN


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
