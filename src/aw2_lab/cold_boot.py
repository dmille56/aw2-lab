"""Bounded cold boot into the fixed, two-player Versus configuration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from struct import unpack_from
from typing import Protocol

from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.lifecycle import BattleControlObservation, LifecyclePhase, classify_lifecycle
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.state_model import GameState, ValueStatus, Weather

_PROCESS_POOL = (0x0200D610, 32 * 0x6C)
_CONTROL = (0x03003F3C, 0xC4)
_CALLBACKS = (0x030040D0, 0x20)
_SETUP = (0x02017C61, 0x16)
_BATTLE_STATE = (0x030032D8, 2)
_LOCK = (0x030030F0, 1)
_INPUT_GATE = (0x030040E4, 2)
_INPUT_STATE = (0x03003334, 2)
_POLL_FRAMES = 30
_MAX_PHASE_FRAMES = 1800
_KEY_A = 1
_KEY_DOWN = 128
_KEY_UP = 64
_KEY_LEFT = 32


class ColdBootError(RuntimeError):
    """Raised when startup, menu navigation, or final configuration is unexpected."""


class CheckpointRecorder(Protocol):
    async def __call__(self, label: str, input_event: dict[str, int] | None) -> None: ...


@dataclass(frozen=True, slots=True)
class ColdBootEvent:
    label: str
    frame: int
    phase: LifecyclePhase
    input: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class ColdBootResult:
    game_state: GameState
    map_id: int
    events: tuple[ColdBootEvent, ...]


@dataclass(frozen=True, slots=True)
class _FrontendState:
    frame: int
    phase: LifecyclePhase
    map_id: int
    setup_subphase: int
    setup: bytes


async def boot_fixed_versus_match(
    bridge: LuaBridgeClient,
    *,
    rom_path: Path,
    checkpoint_recorder: CheckpointRecorder | None = None,
) -> ColdBootResult:
    """Navigate from cartridge boot and verify the fixed first playable turn.

    Inputs are restricted to the sequence observed in a full fresh-save trace.
    Every wait is bounded by a frame budget and each screen boundary uses the
    ROM-specific lifecycle classifier. Setup values and the final playable
    state are checked before returning success.
    """
    select_rom_profile(rom_path)
    events: list[ColdBootEvent] = []

    async def observe() -> _FrontendState:
        ranges = [
            _PROCESS_POOL,
            _CONTROL,
            _CALLBACKS,
            _SETUP,
            _BATTLE_STATE,
            _LOCK,
            _INPUT_GATE,
            _INPUT_STATE,
        ]
        snapshot = await bridge.read_memory_snapshot(ranges)
        pool, control, callbacks, setup, battle_state, lock, gate, input_state = snapshot.ranges
        scripts = tuple(unpack_from("<I", pool, index * 0x6C)[0] for index in range(32))
        lifecycle = classify_lifecycle(
            unpack_from("<I", callbacks)[0],
            unpack_from("<I", callbacks, 0x1C)[0],
            scripts,
            battle_control=BattleControlObservation(
                mode=unpack_from("<I", control)[0],
                state=unpack_from("<H", battle_state)[0],
                lock_count=lock[0],
                input_gate=int.from_bytes(gate, "little", signed=True),
                input_state=unpack_from("<H", input_state)[0],
            ),
        )
        return _FrontendState(
            frame=snapshot.frame,
            phase=lifecycle.phase,
            map_id=control[0x86],
            setup_subphase=setup[0x15],
            setup=setup,
        )

    async def checkpoint(
        label: str,
        state: _FrontendState,
        input_event: dict[str, int] | None = None,
    ) -> None:
        events.append(ColdBootEvent(label, state.frame, state.phase, input_event))
        if checkpoint_recorder is not None:
            await checkpoint_recorder(label, input_event)

    async def tap(label: str, keys: int) -> _FrontendState:
        frame = await bridge.press_keys(keys, 1)
        state = await observe()
        if state.frame != frame:
            raise ColdBootError(
                f"Frame changed after {label}: input ended at {frame}, observed {state.frame}"
            )
        await checkpoint(label, state, {"keys": keys, "frames": 1})
        return state

    async def wait_for(
        phase: LifecyclePhase,
        *,
        budget: int = _MAX_PHASE_FRAMES,
        setup_subphase: int | None = None,
    ) -> _FrontendState:
        state = await observe()
        elapsed = 0
        while not (
            state.phase is phase
            and (setup_subphase is None or state.setup_subphase == setup_subphase)
        ):
            if elapsed >= budget:
                expected = phase.value
                if setup_subphase is not None:
                    expected += f" (setup subphase {setup_subphase})"
                raise ColdBootError(
                    f"Timed out waiting for {expected}; observed {state.phase.value} "
                    f"at frame {state.frame} after {elapsed} frames"
                )
            count = min(_POLL_FRAMES, budget - elapsed)
            end_frame = await bridge.advance_frames(count)
            elapsed += count
            state = await observe()
            if state.frame != end_frame:
                raise ColdBootError(
                    f"Frame changed during lifecycle wait: expected {end_frame}, "
                    f"observed {state.frame}"
                )
        return state

    async def settle(frames: int = _POLL_FRAMES) -> _FrontendState:
        frame = await bridge.advance_frames(frames)
        state = await observe()
        if state.frame != frame:
            raise ColdBootError(
                f"Frame changed during menu settle: expected {frame}, observed {state.frame}"
            )
        return state

    async with asyncio.timeout(180):
        await bridge.connect()
        title = await wait_for(LifecyclePhase.TITLE)
        await checkpoint("title", title)

        # TITLE also covers the attract sequence. The fresh-save trace shows
        # that early taps can be ignored, so retry A while waiting for the
        # accepted input to move the game into mode selection.
        mode_select = await observe()
        title_elapsed = 0
        while mode_select.phase is not LifecyclePhase.MODE_SELECT:
            if title_elapsed >= _MAX_PHASE_FRAMES:
                raise ColdBootError(
                    f"Title did not accept A within {title_elapsed} frames; "
                    f"observed {mode_select.phase.value} at frame {mode_select.frame}"
                )
            event = None
            if mode_select.phase is LifecyclePhase.TITLE:
                end_frame = await bridge.press_keys(_KEY_A, 1)
                event = {"keys": _KEY_A, "frames": 1}
                mode_select = await observe()
                if mode_select.frame != end_frame:
                    raise ColdBootError(
                        f"Frame changed after title A: expected {end_frame}, "
                        f"observed {mode_select.frame}"
                    )
                events.append(
                    ColdBootEvent("title-a-attempt", mode_select.frame, mode_select.phase, event)
                )
                if mode_select.phase is LifecyclePhase.MODE_SELECT:
                    break
            elif mode_select.phase not in {
                LifecyclePhase.BATTLE_TRANSITION,
                LifecyclePhase.UNKNOWN,
            }:
                raise ColdBootError(
                    f"Unexpected phase while leaving title: {mode_select.phase.value}"
                )

            end_frame = await bridge.advance_frames(_POLL_FRAMES)
            mode_select = await observe()
            title_elapsed += _POLL_FRAMES + (1 if event is not None else 0)
            if mode_select.frame != end_frame:
                raise ColdBootError(
                    f"Frame changed during title navigation: expected {end_frame}, "
                    f"observed {mode_select.frame}"
                )
        await checkpoint("mode-select", mode_select, {"keys": _KEY_A, "frames": 1})

        # Let the mode menu finish its transition before moving the cursor.
        # The observed manual trace includes a neutral interval here; without
        # it the first Down can be consumed by the title-to-menu transition.
        mode_select = await settle(120)
        if mode_select.phase is not LifecyclePhase.MODE_SELECT:
            raise ColdBootError(
                f"Leaving mode selection during initial settle: {mode_select.phase.value}"
            )

        await tap("highlight-versus", _KEY_DOWN)
        versus_selected = await settle()
        if versus_selected.phase is not LifecyclePhase.MODE_SELECT:
            raise ColdBootError(
                f"Leaving mode selection after Down: observed {versus_selected.phase.value}"
            )
        await checkpoint("versus-selected", versus_selected)

        await tap("open-versus", _KEY_A)
        new_choice = await settle()
        if new_choice.phase is not LifecyclePhase.MODE_SELECT:
            raise ColdBootError(
                f"Unexpected phase at the Versus New choice: {new_choice.phase.value}"
            )
        await checkpoint("versus-new-choice", new_choice)
        await tap("confirm-versus-new", _KEY_A)

        map_select = await wait_for(LifecyclePhase.VERSUS_MAP_SELECT)
        if map_select.map_id != 1:
            raise ColdBootError(
                f"Bean Island must be selected at map entry; observed map ID {map_select.map_id}"
            )
        map_select = await settle(120)
        if map_select.phase is not LifecyclePhase.VERSUS_MAP_SELECT or map_select.map_id != 1:
            raise ColdBootError(
                "Bean Island selection changed during map-screen settle: "
                f"phase={map_select.phase.value}, map ID={map_select.map_id}"
            )
        await checkpoint("bean-island-selected", map_select)
        await tap("confirm-bean-island", _KEY_A)

        teams = await wait_for(
            LifecyclePhase.VERSUS_SETUP,
            setup_subphase=0,
        )
        _verify_setup(teams)
        await checkpoint("teams-co-setup", teams)

        for label, keys in (
            ("select-team-player", _KEY_LEFT),
            ("select-player-control", _KEY_UP),
            ("select-co-entry", _KEY_LEFT),
            ("select-player-entry", _KEY_LEFT),
            ("select-co-confirmation", _KEY_LEFT),
        ):
            await tap(label, keys)
            await settle()

        await tap("open-rules", _KEY_A)
        rules = await wait_for(LifecyclePhase.VERSUS_SETUP, setup_subphase=2)
        await checkpoint("rules-before-fog-change", rules)

        await tap("disable-fog", _KEY_DOWN)
        rules = await settle()
        if rules.phase is not LifecyclePhase.VERSUS_SETUP or rules.setup_subphase != 2:
            raise ColdBootError(
                f"Unexpected phase after selecting Fog Off: {rules.phase.value}/"
                f"{rules.setup_subphase}"
            )
        await checkpoint("rules-fog-off", rules)

        await tap("start-battle", _KEY_A)
        await wait_for(LifecyclePhase.BATTLE_PLAYER_TURN, budget=1800)
        game_state = await capture_game_state(bridge, rom_path=rom_path)
        map_id = (await bridge.read_memory_snapshot([(0x03003FC2, 1)])).ranges[0][0]
        _verify_playable_state(game_state, map_id)
        ready = await observe()
        await checkpoint("player-one-ready", ready)

    return ColdBootResult(game_state, map_id, tuple(events))


def _verify_setup(state: _FrontendState) -> None:
    teams = state.setup[0:4]
    cos = state.setup[0x0B:0x0F]
    if teams[:2] != bytes((0, 1)):
        raise ColdBootError(
            f"Expected players 1/2 on separate teams A/B; observed {teams[:2].hex()}"
        )
    if cos[:2] != bytes((0, 1)):
        raise ColdBootError(f"Expected Andy/Max selection in slots 1/2; observed {cos[:2].hex()}")


def _verify_playable_state(state: GameState, map_id: int) -> None:
    if state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
        raise ColdBootError(f"Expected a human player turn; observed {state.lifecycle.phase.value}")
    if state.battle.status is not ValueStatus.AVAILABLE or state.battle.value is None:
        raise ColdBootError("Battle state is not validated and available at the first turn")
    battle = state.battle.value
    if map_id != 1 or (battle.map.width, battle.map.height) != (16, 15):
        raise ColdBootError(
            f"Expected Bean Island (map ID 1, 16x15); observed ID {map_id}, "
            f"{battle.map.width}x{battle.map.height}"
        )
    players = {player.slot: player for player in battle.players}
    if set(players) != {1, 2}:
        raise ColdBootError(f"Expected active slots 1 and 2; observed {sorted(players)}")
    expected = {
        1: (1, 1, 0),  # human control, Andy, team A
        2: (1, 2, 1),  # human control, Max, team B
    }
    for slot, (control, co, team) in expected.items():
        player = players[slot]
        observed = (player.control_type, player.co_id, player.team_id)
        if observed != (control, co, team):
            raise ColdBootError(
                f"Player {slot} expected control/CO/team {(control, co, team)}, observed {observed}"
            )
    if battle.day != 1 or battle.active_player_slot != 1:
        raise ColdBootError(
            f"Expected player 1 on day 1; observed player {battle.active_player_slot}, "
            f"day {battle.day}"
        )
    if (
        battle.weather.status is not ValueStatus.AVAILABLE
        or battle.weather.value is not Weather.CLEAR
    ):
        raise ColdBootError("Expected clear weather at the first player turn")
