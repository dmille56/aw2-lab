"""Bounded cold boot into a selected Versus map with configurable players and rules."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from struct import unpack_from
from typing import Literal, Protocol

from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.lifecycle import BattleControlObservation, LifecyclePhase, classify_lifecycle
from aw2_lab.map_catalog import MAPS_BY_ID, MapId, VersusMap
from aw2_lab.match_contract import CO_ID_VALUES, CoId, MatchRules
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.state_model import GameState, ValueStatus, Weather

_PROCESS_POOL = (0x0200D610, 32 * 0x6C)
_CONTROL = (0x03003F3C, 0xC4)
_CALLBACKS = (0x030040D0, 0x20)
_SETUP = (0x02017C61, 0x16)
_SETUP_FOCUS = (0x02017C82, 1)
_BATTLE_STATE = (0x030032D8, 2)
_LOCK = (0x030030F0, 1)
_INPUT_GATE = (0x030040E4, 2)
_INPUT_STATE = (0x03003334, 2)
_FRONTEND_SELECTOR = (0x03001470, 0x80)
_MAP_CATEGORY = (0x0300596C, 1)
# Correlated with the Rules-screen Fog label in fresh and existing save traces.
_FOG_RULE = (0x03001698, 1)
_POLL_FRAMES = 30
_MAX_PHASE_FRAMES = 1800
_KEY_A = 1
_KEY_DOWN = 128
_KEY_UP = 64
_KEY_LEFT = 32
_KEY_RIGHT = 16
_CO_SETUP_INDEX: dict[CoId, int] = {co_id: index for index, co_id in enumerate(CO_ID_VALUES)}
_CO_BATTLE_ID: dict[CoId, int] = {
    "nell": 0,
    "andy": 1,
    "max": 2,
    "olaf": 3,
    "sami": 4,
    "grit": 5,
    "kanbei": 6,
    "sonja": 7,
    "eagle": 8,
    "drake": 9,
    "sturm": 10,
    "flak": 11,
    "lash": 12,
    "adder": 13,
    "hawke": 14,
    "hachi": 15,
    "colin": 16,
    "jess": 17,
    "sensei": 18,
}
_DEFAULT_MATCH_RULES = MatchRules()
_FOG_SELECTOR_INDEX = {True: 0, False: 1}
_WEATHER_SELECTOR_INDEX = {"random": 0, "clear": 1, "rain": 2, "snow": 3}
_WEATHER_MODE = {"clear": 0, "rain": 3, "snow": 3, "random": 1}
# Main-menu and Continue/New selector tables identified in the manual traces.
_VERSUS_MODE_TABLE = 0x086076DF
_CONTINUE_CHOICE_TABLE = 0x0860770A
_NEW_CHOICE_TABLE = 0x0860772B
_OVERWRITE_DIALOG_OBJECT = 0x08489530
_OVERWRITE_DIALOG_TABLE = 0x08610378


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
    setup_focus: int
    selector_object: int
    selector_table: int
    yes_no_selection: int
    fog_rule: int
    weather_rule: int
    income_rule: int
    day_rule: int
    capture_rule: int
    powers_rule: int
    map_category: int = 2
    player_controls: bytes = b"\x01\x01"


async def boot_fixed_versus_match(
    bridge: LuaBridgeClient,
    *,
    rom_path: Path,
    save_mode: Literal["fresh", "existing"] = "fresh",
    map_id: MapId = "bean_island",
    co_ids: tuple[CoId, ...] = ("andy", "max"),
    match_rules: MatchRules = _DEFAULT_MATCH_RULES,
    checkpoint_recorder: CheckpointRecorder | None = None,
    team_ids: tuple[int, ...] | None = None,
) -> ColdBootResult:
    """Navigate from cartridge boot and verify the selected map at the first turn.

    Frontend menu inputs use ROM-specific selector signatures observed in the
    fresh and existing save traces. Existing-save overwrite confirmation is
    accepted only after the expected prompt is recognized in the isolated save
    copy. Every wait is bounded and the final playable state is verified.
    """
    selected_map = MAPS_BY_ID[map_id]
    team_ids = tuple(range(len(co_ids))) if team_ids is None else team_ids
    if (
        len(co_ids) != selected_map.player_count
        or len(team_ids) != len(co_ids)
        or len(set(team_ids)) < 2
        or any(team not in range(len(co_ids)) for team in team_ids)
    ):
        raise ColdBootError("Invalid map player count or team assignments")
    if any(co_id not in _CO_SETUP_INDEX for co_id in co_ids):
        raise ColdBootError("Requested CO selection is not recognized")
    select_rom_profile(rom_path)
    events: list[ColdBootEvent] = []
    rule_addresses = tuple(_FOG_RULE[0] + index * 0x60 for index in range(6))

    async def observe() -> _FrontendState:
        ranges = [
            _PROCESS_POOL,
            _CONTROL,
            _CALLBACKS,
            _SETUP,
            _SETUP_FOCUS,
            _BATTLE_STATE,
            _LOCK,
            _INPUT_GATE,
            _INPUT_STATE,
            _FRONTEND_SELECTOR,
            (rule_addresses[0], 1),
            _MAP_CATEGORY,
            (0x02017C59, 4),
            *((address, 1) for address in rule_addresses[1:]),
        ]
        snapshot = await bridge.read_memory_snapshot(ranges)
        (
            pool,
            control,
            callbacks,
            setup,
            setup_focus,
            battle_state,
            lock,
            gate,
            input_state,
            selector,
            fog_rule,
            map_category,
            player_controls,
            weather_rule,
            income_rule,
            day_rule,
            capture_rule,
            powers_rule,
        ) = snapshot.ranges
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
            setup_focus=setup_focus[0],
            selector_object=unpack_from("<I", selector)[0],
            selector_table=unpack_from("<I", selector, 0x20)[0],
            yes_no_selection=selector[0x7E],
            fog_rule=fog_rule[0],
            map_category=map_category[0],
            player_controls=player_controls,
            weather_rule=weather_rule[0],
            income_rule=income_rule[0],
            day_rule=day_rule[0],
            capture_rule=capture_rule[0],
            powers_rule=powers_rule[0],
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

    async def select_versus(state: _FrontendState) -> _FrontendState:
        if state.phase is not LifecyclePhase.MODE_SELECT:
            raise ColdBootError(f"Expected Select Mode; observed {state.phase.value}")
        if state.selector_table == 0:
            raise ColdBootError("Select Mode has no recognized selector table")

        for index in range(1, 8):
            if state.selector_table == _VERSUS_MODE_TABLE:
                await checkpoint("versus-selected", state)
                return state
            await tap(f"navigate-mode-{index}", _KEY_DOWN)
            state = await settle()
            if state.phase is not LifecyclePhase.MODE_SELECT:
                raise ColdBootError(
                    f"Leaving Select Mode while locating Versus: {state.phase.value}"
                )
            if state.selector_table == 0:
                raise ColdBootError("Mode selection lost its selector table while navigating")
        raise ColdBootError(
            "Versus was not reached within the bounded mode-menu cycle; "
            f"last selector table 0x{state.selector_table:08X}"
        )

    async def wait_for_overwrite_or_map() -> tuple[_FrontendState, bool]:
        state = await observe()
        elapsed = 0
        while True:
            if state.phase is LifecyclePhase.VERSUS_MAP_SELECT:
                return state, False
            if (
                state.phase is LifecyclePhase.MODE_SELECT
                and state.selector_object == _OVERWRITE_DIALOG_OBJECT
                and state.selector_table == _OVERWRITE_DIALOG_TABLE
            ):
                if state.yes_no_selection != 0:
                    raise ColdBootError(
                        "Overwrite prompt is not on Yes; refusing to confirm it "
                        f"(selected row {state.yes_no_selection})"
                    )
                return state, True
            if elapsed >= _MAX_PHASE_FRAMES:
                raise ColdBootError(
                    "Timed out waiting for Bean Island selection or the recognized "
                    "existing-save overwrite prompt; observed "
                    f"{state.phase.value}, object 0x{state.selector_object:08X}, "
                    f"table 0x{state.selector_table:08X} at frame {state.frame}"
                )
            count = min(_POLL_FRAMES, _MAX_PHASE_FRAMES - elapsed)
            end_frame = await bridge.advance_frames(count)
            elapsed += count
            state = await observe()
            if state.frame != end_frame:
                raise ColdBootError(
                    f"Frame changed while awaiting save prompt: expected {end_frame}, "
                    f"observed {state.frame}"
                )

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
        mode_select = await settle(180)
        if mode_select.phase is not LifecyclePhase.MODE_SELECT:
            raise ColdBootError(
                f"Leaving mode selection during initial settle: {mode_select.phase.value}"
            )
        await checkpoint("mode-menu-ready", mode_select)

        await select_versus(mode_select)
        choice = await tap("open-versus", _KEY_A)
        choice = await settle()
        if choice.phase is not LifecyclePhase.MODE_SELECT:
            raise ColdBootError(
                f"Unexpected phase at the Versus Continue/New choice: {choice.phase.value}"
            )
        if choice.selector_table == _CONTINUE_CHOICE_TABLE:
            await checkpoint("versus-continue-selected", choice)
            choice = await tap("select-new-versus", _KEY_DOWN)
            choice = await settle()
        if choice.selector_table != _NEW_CHOICE_TABLE:
            raise ColdBootError(
                "Versus New was not selected; observed selector table "
                f"0x{choice.selector_table:08X}"
            )
        await checkpoint("versus-new-choice", choice)
        await tap("confirm-versus-new", _KEY_A)

        after_new, overwrite_prompt = await wait_for_overwrite_or_map()
        if overwrite_prompt:
            if save_mode != "existing":
                raise ColdBootError(
                    "Unexpected overwrite prompt for fresh-save automation; refusing to confirm it"
                )
            after_new = await settle(_POLL_FRAMES)
            if (
                after_new.selector_object != _OVERWRITE_DIALOG_OBJECT
                or after_new.selector_table != _OVERWRITE_DIALOG_TABLE
                or after_new.yes_no_selection != 0
            ):
                raise ColdBootError(
                    "Existing-save overwrite prompt changed before confirmation; "
                    "refusing to confirm it"
                )
            await checkpoint("overwrite-confirmation", after_new)
            await tap("confirm-overwrite-existing-copy", _KEY_A)

        map_select = (
            after_new if not overwrite_prompt else await wait_for(LifecyclePhase.VERSUS_MAP_SELECT)
        )
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
        if map_select.map_category != 2:
            raise ColdBootError("Expected Classic as the initial map category")
        for category_id in range(3, selected_map.category.selector_id + 1):
            await tap(f"select-map-category-{category_id}", _KEY_RIGHT)
            map_select = await settle(120)
            if (
                map_select.phase is not LifecyclePhase.VERSUS_MAP_SELECT
                or map_select.map_category != category_id
            ):
                raise ColdBootError("Map category input did not reach the expected category")
        # The battle ID is assigned only when A confirms the map. List positions
        # include maps for other player counts, especially in Pre-Deployed/War Room.
        for index in range(selected_map.menu_index):
            await tap(f"select-map-down-{index + 1}", _KEY_DOWN)
            map_select = await settle(120)
            if (
                map_select.phase is not LifecyclePhase.VERSUS_MAP_SELECT
                or map_select.map_category != selected_map.category.selector_id
            ):
                raise ColdBootError("Left the expected category while moving the map highlight")
        await checkpoint(f"{map_id.replace('_', '-')}-selected", map_select)
        await tap(f"confirm-{map_id.replace('_', '-')}", _KEY_A)

        if selected_map.requires_unlock:
            confirmed = await settle(180)
            if confirmed.phase is LifecyclePhase.VERSUS_MAP_SELECT:
                raise ColdBootError(
                    f"{selected_map.name} is not selectable in this save; unlock it in Battle Maps"
                )
        teams = await wait_for(
            LifecyclePhase.VERSUS_SETUP,
            setup_subphase=0,
        )
        if teams.map_id != selected_map.rom_id:
            raise ColdBootError(
                f"Expected {selected_map.name} ID {selected_map.rom_id}; "
                f"map confirmation loaded ID {teams.map_id}"
            )
        teams = await settle()

        async def focus_setup(target: int, subphase: int = 0) -> _FrontendState:
            state = await observe()
            if not 0 <= state.setup_focus <= 3 * len(co_ids):
                raise ColdBootError("Unrecognized Teams cursor")
            for step in range(abs(target - state.setup_focus)):
                expected = state.setup_focus + (1 if target > state.setup_focus else -1)
                await tap(
                    f"focus-setup-{target}-{step}",
                    _KEY_RIGHT if target > state.setup_focus else _KEY_LEFT,
                )
                state = await settle()
                if (
                    state.phase is not LifecyclePhase.VERSUS_SETUP
                    or state.setup_focus != expected
                    or (subphase == 0 and state.setup_subphase != 0)
                ):
                    raise ColdBootError(
                        f"Teams cursor expected {expected}; observed {state.setup_focus}, target {target}"
                    )
            return state

        for index, co_id in enumerate(co_ids):
            teams = await focus_setup(index * 2 + 1)
            if teams.player_controls[index] != 1:
                if teams.player_controls[index] != 2:
                    raise ColdBootError("Unrecognized player control selector")
                await tap(f"set-player-{index + 1}-external", _KEY_UP)
                teams = await settle()
                if teams.player_controls[index] != 1:
                    raise ColdBootError("External player control was not selected")
            teams = await focus_setup(index * 2)
            teams = await _select_setup_co(teams, tap, settle, slot=index + 1, co_id=co_id)
        await checkpoint("players-configured", teams)
        if len(co_ids) > 2:
            await tap("open-team-assignments", _KEY_A)
            teams = await wait_for(LifecyclePhase.VERSUS_SETUP)
            teams = await settle(180)
            for index, team in enumerate(team_ids):
                teams = await focus_setup(index, subphase=1)
                for step in range((team - teams.setup[index]) % len(co_ids)):
                    expected = (teams.setup[index] + 1) % len(co_ids)
                    await tap(f"set-player-{index + 1}-team-{step}", _KEY_DOWN)
                    teams = await settle()
                    if (
                        teams.phase is not LifecyclePhase.VERSUS_SETUP
                        or teams.setup[index] != expected
                    ):
                        raise ColdBootError("Team selector did not reach the expected team")
        _verify_setup(teams, co_ids, team_ids)
        await checkpoint("teams-co-setup", teams)

        await tap("open-rules", _KEY_A)
        rules = await wait_for(LifecyclePhase.VERSUS_SETUP)
        rules = await settle(180)
        if rules.phase is not LifecyclePhase.VERSUS_SETUP:
            raise ColdBootError(
                f"Rules screen did not settle: {rules.phase.value}/{rules.setup_subphase}"
            )
        selector_memory = await bridge.read_memory_snapshot([(0x03001400, 0x1000)])
        rule_addresses = _locate_rule_selectors(selector_memory.ranges[0])
        rules = await observe()
        if rules.fog_rule != 0:
            raise ColdBootError(f"Unexpected initial Fog selector: {rules.fog_rule}")
        await checkpoint("rules-before-fog-change", rules)
        rules = await _select_rule_value(
            rules, tap, settle, "fog_rule", _FOG_SELECTOR_INDEX[match_rules.fog], 1, "fog"
        )
        await checkpoint("rules-fog-on" if match_rules.fog else "rules-fog-off", rules)

        if (
            rules.weather_rule,
            rules.income_rule,
            rules.day_rule,
            rules.capture_rule,
            rules.powers_rule,
        ) != (0, 0, 0, 0, 0):
            raise ColdBootError("Unexpected default rule selectors")
        for field_name, target, maximum, label in (
            (
                "weather_rule",
                _WEATHER_SELECTOR_INDEX[match_rules.starting_weather],
                3,
                "weather",
            ),
            (
                "income_rule",
                match_rules.starting_funds // 500 - 2,
                8,
                "income",
            ),
            (
                "day_rule",
                0 if match_rules.day_limit is None else match_rules.day_limit - 4,
                95,
                "day-limit",
            ),
            (
                "capture_rule",
                0 if match_rules.capture_limit is None else match_rules.capture_limit - 11,
                16,
                "capture-limit",
            ),
            ("powers_rule", 0 if match_rules.co_powers else 1, 1, "co-powers"),
        ):
            await tap(f"focus-{label}-rule", _KEY_RIGHT)
            rules = await settle()
            if rules.phase is not LifecyclePhase.VERSUS_SETUP:
                raise ColdBootError(f"Left the Rules screen while focusing {label}")
            rules = await _select_rule_value(rules, tap, settle, field_name, target, maximum, label)
        _verify_rules(rules, match_rules)
        await checkpoint("verified-configurable-rules", rules)
        await tap("start-battle", _KEY_A)
        await wait_for(LifecyclePhase.BATTLE_PLAYER_TURN, budget=1800)
        game_state = await capture_game_state(bridge, rom_path=rom_path)
        startup_memory = await bridge.read_memory_snapshot([(0x03003FC2, 1), (0x03003FED, 1)])
        loaded_map_id = startup_memory.ranges[0][0]
        weather_mode = startup_memory.ranges[1][0]
        _verify_playable_state(
            game_state, loaded_map_id, selected_map, co_ids, match_rules, weather_mode, team_ids
        )
        ready = await observe()
        await checkpoint("player-one-ready", ready)

    return ColdBootResult(game_state, loaded_map_id, tuple(events))


async def _select_setup_co(
    state: _FrontendState,
    tap: Callable[[str, int], Awaitable[_FrontendState]],
    settle: Callable[[], Awaitable[_FrontendState]],
    *,
    slot: int,
    co_id: CoId,
) -> _FrontendState:
    """Cycle the focused Teams-screen CO and verify each Down/Up input in RAM."""
    expected_focus = 2 * (slot - 1)
    if (
        state.phase is not LifecyclePhase.VERSUS_SETUP
        or state.setup_subphase != 0
        or state.setup_focus != expected_focus
    ):
        raise ColdBootError(
            f"Player {slot} CO selector is not focused; observed setup focus {state.setup_focus}"
        )
    offset = 0x0B + slot - 1
    current = state.setup[offset]
    if current >= 19:
        raise ColdBootError(f"Player {slot} CO setup index is unrecognized: {current}")
    target = _CO_SETUP_INDEX[co_id]
    down_steps = (target - current) % 19
    up_steps = (current - target) % 19
    if min(down_steps, up_steps) == 0:
        return state
    direction, count = (_KEY_DOWN, down_steps) if down_steps <= up_steps else (_KEY_UP, up_steps)
    delta = 1 if direction == _KEY_DOWN else -1
    for index in range(count):
        await tap(f"select-slot-{slot}-co-{index + 1}", direction)
        state = await settle()
        expected = (current + delta * (index + 1)) % 19
        if (
            state.phase is not LifecyclePhase.VERSUS_SETUP
            or state.setup_subphase != 0
            or state.setup_focus != expected_focus
            or state.setup[offset] != expected
        ):
            raise ColdBootError(
                f"Player {slot} CO selector did not reach setup index {expected}; "
                f"observed {state.setup[offset]} at focus {state.setup_focus}"
            )
    if state.setup[offset] != target:
        raise ColdBootError(f"Player {slot} CO selector did not reach {co_id}")
    return state


def _verify_setup(
    state: _FrontendState,
    co_ids: tuple[CoId, ...] | None = ("andy", "max"),
    team_ids: tuple[int, ...] = (0, 1),
) -> None:
    teams = state.setup[0:4]
    if teams[: len(team_ids)] != bytes(team_ids):
        raise ColdBootError(
            f"Expected team IDs {team_ids}; observed {teams[: len(team_ids)].hex()}"
        )
    if co_ids is not None:
        observed_cos = state.setup[0x0B : 0x0B + len(co_ids)]
        expected_cos = bytes(_CO_SETUP_INDEX[co_id] for co_id in co_ids)
        if observed_cos != expected_cos:
            raise ColdBootError(
                f"Expected setup CO indexes {expected_cos.hex()}; observed {observed_cos.hex()}"
            )


async def _select_rule_value(
    state: _FrontendState,
    tap: Callable[[str, int], Awaitable[_FrontendState]],
    settle: Callable[[], Awaitable[_FrontendState]],
    field_name: str,
    target: int,
    maximum: int,
    label: str,
) -> _FrontendState:
    current = getattr(state, field_name)
    if not isinstance(current, int) or not 0 <= current <= maximum:
        raise ColdBootError(f"Unrecognized {label} selector value: {current}")
    direction = _KEY_DOWN if target >= current else _KEY_UP
    for index in range(abs(target - current)):
        state = await tap(f"set-{label}-{index + 1}", direction)
        state = await settle()
        observed = getattr(state, field_name)
        expected = current + (index + 1) * (1 if direction == _KEY_DOWN else -1)
        if state.phase is not LifecyclePhase.VERSUS_SETUP or observed != expected:
            raise ColdBootError(f"{label} selector expected {expected}; observed {observed}")
    if getattr(state, field_name) != target:
        raise ColdBootError(
            f"{label} selector did not reach {target}; observed {getattr(state, field_name)}"
        )
    return state


def _verify_rules(state: _FrontendState, rules: MatchRules = _DEFAULT_MATCH_RULES) -> None:
    expected = (
        _FOG_SELECTOR_INDEX[rules.fog],
        _WEATHER_SELECTOR_INDEX[rules.starting_weather],
        rules.starting_funds // 500 - 2,
        0 if rules.day_limit is None else rules.day_limit - 4,
        0 if rules.capture_limit is None else rules.capture_limit - 11,
        0 if rules.co_powers else 1,
    )
    if (
        state.fog_rule,
        state.weather_rule,
        state.income_rule,
        state.day_rule,
        state.capture_rule,
        state.powers_rule,
    ) != expected:
        raise ColdBootError(f"Rule selectors do not match the requested configuration: {expected}")


def _verify_playable_state(
    state: GameState,
    map_id: int,
    selected_map: VersusMap = MAPS_BY_ID["bean_island"],
    co_ids: tuple[CoId, ...] = ("andy", "max"),
    match_rules: MatchRules = _DEFAULT_MATCH_RULES,
    weather_mode: int = 0,
    team_ids: tuple[int, ...] = (0, 1),
) -> None:
    if state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
        raise ColdBootError(f"Expected a human player turn; observed {state.lifecycle.phase.value}")
    if state.battle.status is not ValueStatus.AVAILABLE or state.battle.value is None:
        raise ColdBootError(
            "Battle state is not validated and available at the first turn: "
            + "; ".join(state.battle.reasons)
        )
    battle = state.battle.value
    if map_id != selected_map.rom_id or (battle.map.width, battle.map.height) != (
        selected_map.width,
        selected_map.height,
    ):
        raise ColdBootError(
            f"Expected {selected_map.name} (map ID {selected_map.rom_id}, "
            f"{selected_map.width}x{selected_map.height}); observed ID {map_id}, "
            f"{battle.map.width}x{battle.map.height}"
        )
    players = {player.slot: player for player in battle.players}
    if set(players) != set(range(1, len(co_ids) + 1)):
        raise ColdBootError(f"Expected {len(co_ids)} active slots; observed {sorted(players)}")
    expected = {
        index: (1, _CO_BATTLE_ID[co], team)
        for index, (co, team) in enumerate(zip(co_ids, team_ids, strict=True), 1)
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
    if battle.weather.status is not ValueStatus.AVAILABLE or battle.weather.value is None:
        raise ColdBootError("Starting weather is unavailable at the first player turn")
    weather = match_rules.starting_weather
    expected_weather = {"clear": Weather.CLEAR, "rain": Weather.RAIN, "snow": Weather.SNOW}
    if weather == "random":
        if weather_mode != _WEATHER_MODE[weather]:
            raise ColdBootError(
                f"Random weather expected mode {_WEATHER_MODE[weather]}, observed {weather_mode}"
            )
    elif (
        battle.weather.value is not expected_weather[weather]
        or weather_mode != _WEATHER_MODE[weather]
    ):
        raise ColdBootError(
            f"Expected {weather} weather/mode {_WEATHER_MODE[weather]}, observed "
            f"{battle.weather.value.value}/{weather_mode}"
        )

    if (
        battle.fog_enabled.status is not ValueStatus.AVAILABLE
        or battle.fog_enabled.value is not match_rules.fog
    ):
        raise ColdBootError(
            f"Fog {'On' if match_rules.fog else 'Off'} was not observed at the playable boundary"
        )
    if (
        battle.co_effects_enabled.status is not ValueStatus.AVAILABLE
        or battle.co_effects_enabled.value is not match_rules.co_powers
    ):
        raise ColdBootError("CO power rule did not match the playable boundary")
    # At day one Red has received one income payment. Count actual owned
    # properties rather than carrying Bean Island's opening balance to other maps.
    income_properties = sum(
        prop.owner_slot == 1 and prop.terrain_class in (6, 8, 10, 11, 14)
        for prop in battle.properties
    )
    expected_funds = (income_properties * match_rules.starting_funds, 0)
    if (players[1].funds, players[2].funds) != expected_funds:
        raise ColdBootError(
            f"Initial funds do not match {selected_map.name} income "
            f"{match_rules.starting_funds}: expected {expected_funds}, "
            f"observed {(players[1].funds, players[2].funds)}"
        )


def _locate_rule_selectors(data: bytes) -> tuple[int, ...]:
    """Locate live Rules selector objects by their pinned-ROM callbacks and headers."""
    callbacks = (0x08064739, 0x08064775, 0x080647BD, 0x0806486D, 0x08064919)
    found: dict[int, list[int]] = {callback: [] for callback in callbacks}
    for offset in range(0x48, len(data) - 4, 4):
        callback = unpack_from("<I", data, offset + 4)[0]
        if callback in found and data[offset - 0x48 : offset - 0x40] == bytes.fromhex(
            "6c09580884095808"
        ):
            found[callback].append(0x03001400 + offset)
    if tuple(len(found[callback]) for callback in callbacks) != (2, 1, 1, 1, 1):
        raise ColdBootError("Rules selector object signatures are not recognized")
    shared = sorted(found[callbacks[0]])
    return (shared[0], *(found[callback][0] for callback in callbacks[1:]), shared[1])
