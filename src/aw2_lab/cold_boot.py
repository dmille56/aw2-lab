"""Bounded cold boot into a selected two-player Versus map with fixed COs/rules."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from struct import unpack_from
from typing import Literal, Protocol

from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.lifecycle import BattleControlObservation, LifecyclePhase, classify_lifecycle
from aw2_lab.map_catalog import MAPS_BY_ID, MapId, VersusMap
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


async def boot_fixed_versus_match(
    bridge: LuaBridgeClient,
    *,
    rom_path: Path,
    save_mode: Literal["fresh", "existing"] = "fresh",
    map_id: MapId = "bean_island",
    checkpoint_recorder: CheckpointRecorder | None = None,
) -> ColdBootResult:
    """Navigate from cartridge boot and verify the selected map at the first turn.

    Frontend menu inputs use ROM-specific selector signatures observed in the
    fresh and existing save traces. Existing-save overwrite confirmation is
    accepted only after the expected prompt is recognized in the isolated save
    copy. Every wait is bounded and the final playable state is verified.
    """
    selected_map = MAPS_BY_ID[map_id]
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
            _FRONTEND_SELECTOR,
            _FOG_RULE,
            _MAP_CATEGORY,
            *((_FOG_RULE[0] + index * 0x60, 1) for index in range(1, 6)),
        ]
        snapshot = await bridge.read_memory_snapshot(ranges)
        (
            pool,
            control,
            callbacks,
            setup,
            battle_state,
            lock,
            gate,
            input_state,
            selector,
            fog_rule,
            map_category,
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
            selector_object=unpack_from("<I", selector)[0],
            selector_table=unpack_from("<I", selector, 0x20)[0],
            yes_no_selection=selector[0x7E],
            fog_rule=fog_rule[0],
            map_category=map_category[0],
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
        for label, keys in (
            ("select-team-player", _KEY_LEFT),
            ("select-player-control", _KEY_UP),
            ("select-co-entry", _KEY_LEFT),
            ("select-player-entry", _KEY_LEFT),
            ("select-co-confirmation", _KEY_LEFT),
        ):
            await tap(label, keys)
            await settle()

        teams = await observe()
        if teams.phase is not LifecyclePhase.VERSUS_SETUP or teams.setup_subphase != 0:
            raise ColdBootError(
                f"Unexpected phase after team/CO setup: {teams.phase.value}/{teams.setup_subphase}"
            )
        _verify_setup(teams)
        await checkpoint("teams-co-setup", teams)

        await tap("open-rules", _KEY_A)
        rules = await wait_for(LifecyclePhase.VERSUS_SETUP, setup_subphase=2)
        rules = await settle()
        if rules.phase is not LifecyclePhase.VERSUS_SETUP or rules.setup_subphase != 2:
            raise ColdBootError(
                f"Rules screen did not settle: {rules.phase.value}/{rules.setup_subphase}"
            )
        if rules.fog_rule != 0:
            raise ColdBootError(
                "Expected Fog to be ON before changing the default; "
                f"observed runtime flag {rules.fog_rule}"
            )
        await checkpoint("rules-before-fog-change", rules)

        await tap("disable-fog", _KEY_DOWN)
        rules = await settle()
        if rules.phase is not LifecyclePhase.VERSUS_SETUP or rules.setup_subphase != 2:
            raise ColdBootError(
                f"Unexpected phase after selecting Fog Off: {rules.phase.value}/"
                f"{rules.setup_subphase}"
            )
        if rules.fog_rule != 1:
            raise ColdBootError(
                "Fog Off input did not set the verified Rules flag; "
                f"observed runtime flag {rules.fog_rule}"
            )
        await checkpoint("rules-fog-off", rules)

        # The stock defaults are Random weather and no turn limit. The runtime
        # profile requires Clear and 30 days. These selectors were correlated
        # with their on-screen values in the pinned ROM (see runtime evidence).
        if (
            rules.weather_rule,
            rules.income_rule,
            rules.day_rule,
            rules.capture_rule,
            rules.powers_rule,
        ) != (0, 0, 0, 0, 0):
            raise ColdBootError("Unexpected default rule selectors")
        await tap("select-weather-rule", _KEY_RIGHT)
        await settle()
        await tap("set-clear-weather", _KEY_DOWN)
        rules = await settle()
        if rules.weather_rule != 1:
            raise ColdBootError("Clear weather selector was not verified")
        await tap("select-income-rule", _KEY_RIGHT)
        await settle()
        await tap("select-day-limit-rule", _KEY_RIGHT)
        await settle()
        for index in range(1, 27):  # OFF -> 5, then one day per Down, ending at 30.
            await tap("increase-day-limit", _KEY_DOWN)
            rules = await settle()
            if rules.day_rule != index:
                raise ColdBootError("Day limit selector did not advance as expected")
        _verify_rules(rules)
        await checkpoint("verified-fixed-rules", rules)
        await tap("start-battle", _KEY_A)
        await wait_for(LifecyclePhase.BATTLE_PLAYER_TURN, budget=1800)
        game_state = await capture_game_state(bridge, rom_path=rom_path)
        loaded_map_id = (await bridge.read_memory_snapshot([(0x03003FC2, 1)])).ranges[0][0]
        _verify_playable_state(game_state, loaded_map_id, selected_map)
        ready = await observe()
        await checkpoint("player-one-ready", ready)

    return ColdBootResult(game_state, loaded_map_id, tuple(events))


def _verify_setup(state: _FrontendState) -> None:
    teams = state.setup[0:4]
    if teams[:2] != bytes((0, 1)):
        raise ColdBootError(
            f"Expected players 1/2 on separate teams A/B; observed {teams[:2].hex()}"
        )


def _verify_rules(state: _FrontendState) -> None:
    if (
        state.fog_rule,
        state.weather_rule,
        state.income_rule,
        state.day_rule,
        state.capture_rule,
        state.powers_rule,
    ) != (1, 1, 0, 26, 0, 0):
        raise ColdBootError(
            "Rule selectors do not match fog Off, Clear, income 1000, 30 days, capture Off and powers On"
        )


def _verify_playable_state(
    state: GameState, map_id: int, selected_map: VersusMap = MAPS_BY_ID["bean_island"]
) -> None:
    if state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
        raise ColdBootError(f"Expected a human player turn; observed {state.lifecycle.phase.value}")
    if state.battle.status is not ValueStatus.AVAILABLE or state.battle.value is None:
        raise ColdBootError("Battle state is not validated and available at the first turn")
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

    if (
        battle.fog_enabled.status is not ValueStatus.AVAILABLE
        or battle.fog_enabled.value is not False
    ):
        raise ColdBootError("Fog Off was not observed at the playable boundary")
    if (
        battle.co_effects_enabled.status is not ValueStatus.AVAILABLE
        or battle.co_effects_enabled.value is not True
    ):
        raise ColdBootError("CO effects On was not observed at the playable boundary")
    # At day one Red has received one income payment. Count actual owned
    # properties rather than carrying Bean Island's opening balance to other maps.
    income_properties = sum(
        prop.owner_slot == 1 and prop.terrain_class in (6, 8, 10, 11, 14)
        for prop in battle.properties
    )
    expected_funds = (income_properties * 1000, 0)
    if (players[1].funds, players[2].funds) != expected_funds:
        raise ColdBootError(
            f"Initial funds do not match {selected_map.name} income 1000: {expected_funds}"
        )
