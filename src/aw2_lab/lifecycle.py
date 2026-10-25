"""Conservative lifecycle classification for the supported AW2 ROM profile.

This module recognizes only screen/process and controller associations documented in
``docs/AW2-LIFECYCLE-RESEARCH.org``. A battle callback identifies the battle
engine family, not a settled or actionable battle. Unknown and conflicting
signals therefore never authorize active-battle decoding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class LifecyclePhase(StrEnum):
    """Observed screen or engine phase, with ambiguous states kept explicit."""

    UNKNOWN = "unknown"
    STARTUP = "startup"
    TITLE = "title"
    MODE_SELECT = "mode_select"
    VERSUS_MAP_SELECT = "versus_map_select"
    VERSUS_SETUP = "versus_setup"
    BATTLE_TRANSITION = "battle_transition"
    BATTLE_PLAYER_TURN = "battle_player_turn"
    BATTLE_ENGINE_UNRESOLVED = "battle_engine_unresolved"
    RESULT_SEQUENCE = "result_sequence"
    VICTORY_PRESENTATION = "victory_presentation"
    DEFEAT_PRESENTATION = "defeat_presentation"
    RESULT_SUMMARY = "result_summary"
    SAVE_PROGRESS_PROMPT = "save_progress_prompt"


class LifecycleEngine(StrEnum):
    """The engine family selected by the observed callback pair."""

    UNKNOWN = "unknown"
    SCREEN = "screen"
    BATTLE = "battle"


class BattleDecodeSafety(StrEnum):
    """Whether memory may be decoded as an active battle state."""

    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LifecycleAssessment:
    """Conservative lifecycle result for one coherent memory observation."""

    phase: LifecyclePhase
    engine: LifecycleEngine
    battle_decode_safety: BattleDecodeSafety
    matched_scripts: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class BattleControlObservation:
    """Battle controller fields from the same frame as the lifecycle signals.

    Addresses for the supported ROM: mode is u32 at 0x03003F3C, state is
    u16 at 0x030032D8, lock_count is u8 at 0x030030F0, input_gate is i16
    at 0x030040E4, and input_state is u16 at 0x03003334 (little endian).
    These fields persist in menus and must not be used without engine checks.
    """

    mode: int
    state: int
    lock_count: int
    input_gate: int
    input_state: int


SCREEN_CALLBACKS = (0x08036885, 0x080368E9)
BATTLE_CALLBACKS = (0x08036945, 0x080369BD)

_FRONTEND_SCRIPTS = {
    0x08581500: LifecyclePhase.STARTUP,
    0x08581C68: LifecyclePhase.TITLE,
    0x0849E818: LifecyclePhase.MODE_SELECT,
    0x0849ECE0: LifecyclePhase.VERSUS_SETUP,
}
_MAP_SELECT_SCRIPT = 0x08616C54
_BATTLE_TRANSITION_SCRIPTS = frozenset({0x0848927C, 0x0848929C, 0x084892C4, 0x0849E750, 0x08499E18})
_RESULT_SCRIPTS = {
    0x0849D56C: LifecyclePhase.RESULT_SEQUENCE,
    0x08615CB0: LifecyclePhase.VICTORY_PRESENTATION,
    0x08615DD8: LifecyclePhase.VICTORY_PRESENTATION,
    0x08615FB4: LifecyclePhase.RESULT_SUMMARY,
    0x084C327C: LifecyclePhase.DEFEAT_PRESENTATION,
    0x0849F330: LifecyclePhase.SAVE_PROGRESS_PROMPT,
}
_RESULT_PRECEDENCE = (
    LifecyclePhase.SAVE_PROGRESS_PROMPT,
    LifecyclePhase.RESULT_SUMMARY,
    LifecyclePhase.VICTORY_PRESENTATION,
    LifecyclePhase.DEFEAT_PRESENTATION,
    LifecyclePhase.RESULT_SEQUENCE,
)
_CONFLICTING_RESULT_PHASES = frozenset(
    {LifecyclePhase.VICTORY_PRESENTATION, LifecyclePhase.DEFEAT_PRESENTATION}
)


def classify_lifecycle(
    callback_a: int,
    callback_b: int,
    process_script_ids: Iterable[int],
    *,
    battle_control: BattleControlObservation | None = None,
) -> LifecycleAssessment:
    """Classify known lifecycle evidence without guessing during ambiguous phases.

    Callback values are compared exactly, including the Thumb low bit. Script
    identifiers must come from the bounded screen-process pool by checking each
    slot's script word. A zero script word is an inactive slot; its remaining
    bytes must not be interpreted as a process.

    Optional controller fields recognize the verified human map-input mode.
    Without those fields, settled battle states and process-free transition
    gaps remain ``BATTLE_ENGINE_UNRESOLVED``. Player-turn recognition does not
    certify field validity or that every command is currently available;
    ``battle_decode_safety`` remains unknown for that phase.
    """
    scripts = frozenset(script for script in process_script_ids if script != 0)
    matched_scripts = tuple(sorted(scripts & (set(_FRONTEND_SCRIPTS) | {_MAP_SELECT_SCRIPT})))
    result_scripts = tuple(sorted(scripts & _RESULT_SCRIPTS.keys()))
    engine = _engine_for(callback_a, callback_b)

    # Result and prompt processes take precedence because the battle callbacks
    # can remain selected during defeat presentation and battle data persists
    # after the match ends.
    if result_scripts:
        result_phases = {_RESULT_SCRIPTS[script] for script in result_scripts}
        if _CONFLICTING_RESULT_PHASES <= result_phases:
            return LifecycleAssessment(
                LifecyclePhase.UNKNOWN,
                engine,
                BattleDecodeSafety.UNKNOWN,
                result_scripts,
            )
        phase = next(phase for phase in _RESULT_PRECEDENCE if phase in result_phases)
        return LifecycleAssessment(
            phase,
            engine,
            BattleDecodeSafety.BLOCKED,
            result_scripts,
        )

    if _MAP_SELECT_SCRIPT in scripts:
        if engine is LifecycleEngine.SCREEN:
            return LifecycleAssessment(
                LifecyclePhase.VERSUS_MAP_SELECT,
                engine,
                BattleDecodeSafety.BLOCKED,
                (_MAP_SELECT_SCRIPT,),
            )
        return LifecycleAssessment(
            LifecyclePhase.UNKNOWN,
            engine,
            BattleDecodeSafety.UNKNOWN,
            (_MAP_SELECT_SCRIPT,),
        )

    # These effects also run at ordinary turn changes, so their presence cannot
    # distinguish initial battle entry from an ongoing match's turn transition.
    if scripts & _BATTLE_TRANSITION_SCRIPTS and engine in {
        LifecycleEngine.SCREEN,
        LifecycleEngine.BATTLE,
    }:
        return LifecycleAssessment(
            LifecyclePhase.BATTLE_TRANSITION,
            engine,
            BattleDecodeSafety.BLOCKED,
            tuple(sorted(scripts & _BATTLE_TRANSITION_SCRIPTS)),
        )

    frontend_matches = tuple(sorted(scripts & _FRONTEND_SCRIPTS.keys()))
    if frontend_matches:
        phases = {_FRONTEND_SCRIPTS[script] for script in frontend_matches}
        if engine is LifecycleEngine.SCREEN and len(phases) == 1:
            return LifecycleAssessment(
                phases.pop(), engine, BattleDecodeSafety.BLOCKED, frontend_matches
            )
        return LifecycleAssessment(
            LifecyclePhase.UNKNOWN,
            engine,
            BattleDecodeSafety.UNKNOWN,
            frontend_matches,
        )

    if engine is LifecycleEngine.BATTLE:
        if (
            not scripts
            and battle_control is not None
            and battle_control.mode == 1
            and battle_control.state == 13
            and battle_control.lock_count == 0
            and battle_control.input_gate == 0
            and battle_control.input_state == 0
        ):
            return LifecycleAssessment(
                LifecyclePhase.BATTLE_PLAYER_TURN,
                engine,
                BattleDecodeSafety.UNKNOWN,
            )
        return LifecycleAssessment(
            LifecyclePhase.BATTLE_ENGINE_UNRESOLVED,
            engine,
            BattleDecodeSafety.UNKNOWN,
        )

    return LifecycleAssessment(
        LifecyclePhase.UNKNOWN,
        engine,
        BattleDecodeSafety.UNKNOWN,
        matched_scripts,
    )


def _engine_for(callback_a: int, callback_b: int) -> LifecycleEngine:
    if (callback_a, callback_b) == SCREEN_CALLBACKS:
        return LifecycleEngine.SCREEN
    if (callback_a, callback_b) == BATTLE_CALLBACKS:
        return LifecycleEngine.BATTLE
    return LifecycleEngine.UNKNOWN
