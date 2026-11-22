"""ROM-independent validation for bounded action navigation."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import (
    ActionNavigator,
    NavigationError,
    NavigationLimits,
    validate_path,
)
from aw2_lab.lifecycle import BattleDecodeSafety, LifecyclePhase
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.production_rules import PRODUCTION_BY_TERRAIN
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import GameState, ObservedValue, ValueStatus
from aw2_lab.ui_state import (
    CursorStatus,
    MenuFamily,
    MenuItem,
    MenuObservation,
    SelectedUnitObservation,
)


def test_validate_path_accepts_empty_and_adjacent_routes() -> None:
    assert validate_path((), start=(1, 1), width=3, height=3) == ()
    assert validate_path(((1, 2), (2, 2)), start=(1, 1), width=3, height=3) == (
        (1, 2),
        (2, 2),
    )


@pytest.mark.parametrize(
    ("path", "start", "width", "height", "message"),
    [
        (((2, 1),), (0, 1), 3, 3, "adjacent"),
        (((3, 1),), (1, 1), 3, 3, "outside"),
        (((True, 1),), (0, 1), 3, 3, "integer pairs"),
        ((), (0, 0), 0, 3, "dimensions"),
    ],
)
def test_validate_path_rejects_invalid_shape(
    path, start, width: int, height: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_path(path, start=start, width=width, height=height)


def test_navigation_limits_reject_unbounded_or_invalid_values() -> None:
    with pytest.raises(ValueError):
        NavigationLimits(frame_budget=0)
    with pytest.raises(ValueError):
        NavigationLimits(wall_timeout=0)


def test_artillery_purchase_uses_resolution_timeout_for_all_rows(memory, monkeypatch) -> None:
    limits = NavigationLimits(wall_timeout=15, resolution_wall_timeout=60)
    real_timeout = asyncio.timeout
    timeouts = []

    def record_timeout(delay):
        timeouts.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", record_timeout)
    initial = decode_snapshot(snapshot(memory))
    menu = MenuObservation(
        initial.frame,
        MenuFamily.PRODUCTION_CHOICES,
        production_unit_types=PRODUCTION_BY_TERRAIN[14].unit_types,
        selected_production_index=0,
    )

    class PurchaseBridge:
        frame = initial.frame
        row = 0
        confirmed = False

        async def observe(self) -> GameState:
            current_menu = (
                MenuObservation(self.frame, MenuFamily.MAP_INPUT)
                if self.confirmed
                else replace(menu, frame=self.frame, selected_production_index=self.row)
            )
            return replace(
                initial,
                frame=self.frame,
                validation=replace(initial.validation, frame=self.frame),
                ui=replace(
                    initial.ui,
                    frame=self.frame,
                    map_cursor=replace(initial.ui.map_cursor, frame=self.frame),
                    menu=current_menu,
                ),
            )

        async def advance_frames(self, frames: int) -> int:
            self.frame += frames
            return self.frame

        async def press_keys(self, keys: int, frames: int) -> int:
            if keys == 128:
                self.row += 1
            else:
                assert keys == 1
                assert menu.production_unit_types[self.row] == 10
                self.confirmed = True
            return await self.advance_frames(frames)

    bridge = PurchaseBridge()
    navigator = ActionNavigator(bridge, bridge.observe, limits=limits)

    result = asyncio.run(navigator.choose_purchase_unit(10))

    assert result.ui.menu.family is MenuFamily.MAP_INPUT
    assert [event.name for event in navigator.inputs] == ["purchase-menu-down"] * 7 + [
        "confirm-purchase"
    ]
    assert timeouts == [limits.resolution_wall_timeout]


def test_unit_selection_uses_resolution_timeout_for_cursor_travel(memory, monkeypatch) -> None:
    state = decode_snapshot(snapshot(memory))
    observation = MatchObservationTracker(uuid4()).commit_boundary(state)
    unit_id = observation.unit_identities[0].identity_id
    limits = NavigationLimits()
    real_timeout = asyncio.timeout
    timeouts = []

    def record_timeout(delay):
        timeouts.append(delay)
        return real_timeout(delay)

    async def observe() -> GameState:
        return state

    async def stalled_cursor(self, x, y):
        assert (x, y) == (0, 0)
        raise TimeoutError

    navigator = ActionNavigator(None, observe, limits=limits)
    monkeypatch.setattr(asyncio, "timeout", record_timeout)
    monkeypatch.setattr(ActionNavigator, "_move_cursor", stalled_cursor)

    with pytest.raises(NavigationError, match="wall-clock watchdog expired"):
        asyncio.run(navigator.select_unit(unit_id, observation))
    assert timeouts == [limits.resolution_wall_timeout]


@pytest.mark.parametrize(
    ("open_production", "target", "exhausted"),
    [
        pytest.param(False, (1, 1), False, id="cursor"),
        pytest.param(True, (1, 1), False, id="production"),
        pytest.param(True, (19, 0), False, id="production-confirm-fits"),
        pytest.param(True, (20, 0), True, id="production-confirm-exceeds-budget"),
        pytest.param(False, (21, 0), True, id="cursor-exceeds-budget"),
    ],
)
def test_map_cursor_waits_for_directional_input_to_rearm(
    memory, monkeypatch, open_production: bool, target: tuple[int, int], exhausted: bool
) -> None:
    real_timeout = asyncio.timeout
    timeouts = []

    def record_timeout(delay):
        timeouts.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", record_timeout)

    class RearmingBridge:
        def __init__(self, state: GameState) -> None:
            self.state = state
            self.released_frames = 0
            self.release_gaps: list[int] = []

        async def observe(self) -> GameState:
            return self.state

        async def advance_frames(self, frames: int) -> int:
            self.released_frames += frames
            self._update(frames)
            return self.state.frame

        async def press_keys(self, keys: int, frames: int) -> int:
            cursor = self.state.ui.map_cursor
            x, y = cursor.x, cursor.y
            if keys in {16, 32, 64, 128}:
                self.release_gaps.append(self.released_frames)
                if self.released_frames >= 8:
                    x += 1 if keys == 16 else -1 if keys == 32 else 0
                    y += 1 if keys == 128 else -1 if keys == 64 else 0
                self.released_frames = 0
            self._update(frames, cursor_position=(x, y))
            if keys == 1:
                self.state = replace(
                    self.state,
                    ui=replace(
                        self.state.ui,
                        menu=MenuObservation(self.state.frame, MenuFamily.PRODUCTION_CHOICES),
                    ),
                )
            return self.state.frame

        def _update(self, frames: int, *, cursor_position=None) -> None:
            frame = self.state.frame + frames
            cursor = replace(
                self.state.ui.map_cursor,
                frame=frame,
                x=(
                    cursor_position[0]
                    if cursor_position is not None
                    else self.state.ui.map_cursor.x
                ),
                y=(
                    cursor_position[1]
                    if cursor_position is not None
                    else self.state.ui.map_cursor.y
                ),
            )
            self.state = replace(
                self.state,
                frame=frame,
                validation=replace(self.state.validation, frame=frame),
                ui=replace(
                    self.state.ui,
                    frame=frame,
                    map_cursor=cursor,
                    menu=replace(self.state.ui.menu, frame=frame),
                ),
            )

    async def run() -> None:
        initial = decode_snapshot(snapshot(memory))
        battle = initial.battle.value
        assert battle is not None
        initial = replace(
            initial,
            battle=replace(
                initial.battle,
                value=replace(battle, map=replace(battle.map, width=22)),
            ),
            ui=replace(
                initial.ui,
                menu=MenuObservation(initial.frame, MenuFamily.MAP_INPUT),
                map_cursor=replace(
                    initial.ui.map_cursor,
                    x=0,
                    y=0,
                    status=CursorStatus.AVAILABLE,
                ),
            ),
        )
        bridge = RearmingBridge(initial)
        navigator = ActionNavigator(bridge, bridge.observe)

        if exhausted:
            with pytest.raises(NavigationError, match="Navigation frame budget exhausted") as error:
                if open_production:
                    await navigator.open_production_menu(*target)
                else:
                    await navigator.move_cursor_to(*target)
            assert (error.value.context.cursor_x, error.value.context.cursor_y) == (20, 0)
            assert len(error.value.context.input_sequence) == 20
            assert bridge.release_gaps == [8] * 20
            return
        if open_production:
            result = await navigator.open_production_menu(*target)
            assert result.ui.menu.family is MenuFamily.PRODUCTION_CHOICES
            assert timeouts == [navigator.limits.resolution_wall_timeout]
        else:
            result = await navigator.move_cursor_to(*target)
            assert timeouts == [navigator.limits.wall_timeout]

        assert (result.ui.map_cursor.x, result.ui.map_cursor.y) == target
        assert bridge.release_gaps == [8] * sum(target)

    asyncio.run(run())


def test_navigate_menu_tracks_each_verified_command_row(memory) -> None:
    class FakeBridge:
        def __init__(self, state: GameState) -> None:
            self.state = state
            self.keys: list[int] = []
            self.timeline: list[tuple[str, int]] = []

        async def observe(self) -> GameState:
            return self.state

        async def press_keys(self, keys: int, frames: int) -> int:
            self.keys.append(keys)
            self.timeline.append(("press", keys))
            if keys == 1:
                if self.state.ui.menu.selected_item is MenuItem.INTEL:
                    self._update(frames, MenuItem.STATUS, family=MenuFamily.INTEL)
                else:
                    self._update(frames, MenuItem.DELETE, family=MenuFamily.OPTIONS)
            elif keys == 2:
                self._update(frames, MenuItem.INTEL, family=MenuFamily.COMMAND)
            else:
                rows = {
                    MenuFamily.COMMAND: (
                        MenuItem.CO,
                        MenuItem.INTEL,
                        MenuItem.POWER,
                        MenuItem.SUPER_POWER,
                        MenuItem.OPTIONS,
                        MenuItem.SAVE,
                        MenuItem.END,
                    ),
                    MenuFamily.INTEL: (MenuItem.STATUS, MenuItem.UNIT, MenuItem.RULES),
                    MenuFamily.OPTIONS: (
                        MenuItem.DELETE,
                        MenuItem.YIELD,
                        MenuItem.MUSIC,
                        MenuItem.VISUAL_MODE,
                        MenuItem.EXIT_MAP,
                    ),
                }[self.state.ui.menu.family]
                index = rows.index(self.state.ui.menu.selected_item) + (1 if keys == 128 else -1)
                self._update(frames, rows[index])
            return self.state.frame

        async def advance_frames(self, frames: int) -> int:
            self._update(frames, self.state.ui.menu.selected_item)
            return self.state.frame

        def _update(self, frames: int, item: MenuItem, *, family: MenuFamily | None = None) -> None:
            frame = self.state.frame + frames
            menu = replace(
                self.state.ui.menu,
                frame=frame,
                family=family or self.state.ui.menu.family,
                selected_item=item,
                actionable=True,
            )
            cursor = replace(self.state.ui.map_cursor, frame=frame)
            ui = replace(self.state.ui, frame=frame, map_cursor=cursor, menu=menu)
            validation = replace(self.state.validation, frame=frame)
            self.state = replace(self.state, frame=frame, validation=validation, ui=ui)

    async def run() -> None:
        initial = decode_snapshot(snapshot(memory))
        command_menu = MenuObservation(
            initial.frame,
            MenuFamily.COMMAND,
            selected_item=MenuItem.CO,
            actionable=True,
        )
        initial = replace(initial, ui=replace(initial.ui, menu=command_menu))
        bridge = FakeBridge(initial)
        navigator = ActionNavigator(bridge, bridge.observe)

        result = await navigator.navigate_menu(MenuItem.RULES)

        assert result.ui.menu.family is MenuFamily.INTEL
        assert result.ui.menu.selected_item is MenuItem.RULES
        assert bridge.keys == [128, 1, 128, 128]
        assert [event.name for event in navigator.inputs] == [
            "menu-down",
            "open-intel-submenu",
            "menu-down",
            "menu-down",
        ]

        result = await navigator.navigate_menu(MenuItem.VISUAL_MODE)

        assert result.ui.menu.family is MenuFamily.OPTIONS
        assert result.ui.menu.selected_item is MenuItem.VISUAL_MODE
        assert bridge.keys == [128, 1, 128, 128, 2, 128, 128, 128, 1, 128, 128, 128]
        assert [event.name for event in navigator.inputs] == [
            "menu-back-to-command",
            "menu-down",
            "menu-down",
            "menu-down",
            "open-options-submenu",
            "menu-down",
            "menu-down",
            "menu-down",
        ]

    asyncio.run(run())


@pytest.mark.parametrize("available", [True, False])
def test_choose_unload_tracks_drop_target_cursor_before_confirmation(memory, available) -> None:
    class FakeBridge:
        def __init__(self, state: GameState) -> None:
            self.state = state
            self.keys: list[int] = []
            self.gaps: list[int] = []

        async def observe(self) -> GameState:
            await asyncio.sleep(0.01)
            return self.state

        async def advance_frames(self, frames: int) -> int:
            self.gaps.append(frames)
            self._update(frames)
            return self.state.frame

        async def press_keys(self, keys: int, frames: int) -> int:
            self.keys.append(keys)
            menu = self.state.ui.menu
            if menu.family is MenuFamily.UNIT_ACTION_CHOICES and keys == 64:
                menu = replace(menu, selected_item=MenuItem.UNLOAD)
            elif menu.family is MenuFamily.UNIT_ACTION_CHOICES and keys == 1:
                menu = MenuObservation(
                    menu.frame,
                    MenuFamily.UNIT_DROP_TARGETING,
                    selected_unit=menu.selected_unit,
                    actionable=True,
                )
            elif menu.family is MenuFamily.UNIT_DROP_TARGETING and keys == 1:
                menu = MenuObservation(
                    menu.frame,
                    MenuFamily.UNIT_ACTION_CHOICES,
                    selected_unit=menu.selected_unit,
                    selected_item=MenuItem.WAIT,
                    actionable=True,
                    items=(MenuItem.WAIT,),
                )
            cursor = self.state.ui.map_cursor
            x, y = cursor.x, cursor.y
            if menu.family is MenuFamily.UNIT_DROP_TARGETING:
                targets = ((1, 0), (2, 1), (1, 2), (0, 1))
                if keys == 1:
                    x, y = targets[0]
                elif keys == 16:
                    x, y = targets[(targets.index((x, y)) + 1) % len(targets)]
            self._update(frames, menu=menu, cursor_position=(x, y))
            return self.state.frame

        def _update(self, frames: int, *, menu=None, cursor_position=None) -> None:
            frame = self.state.frame + frames
            next_menu = replace(menu or self.state.ui.menu, frame=frame)
            cursor = replace(
                self.state.ui.map_cursor,
                frame=frame,
                x=cursor_position[0] if cursor_position is not None else self.state.ui.map_cursor.x,
                y=cursor_position[1] if cursor_position is not None else self.state.ui.map_cursor.y,
                status=CursorStatus.AVAILABLE,
            )
            self.state = replace(
                self.state,
                frame=frame,
                validation=replace(self.state.validation, frame=frame),
                ui=replace(
                    self.state.ui,
                    frame=frame,
                    menu=next_menu,
                    map_cursor=cursor,
                ),
            )

    async def run() -> None:
        initial = decode_snapshot(snapshot(memory))
        selected = SelectedUnitObservation(0x02022690, 1, 1, 23, 1, 1)
        menu = MenuObservation(
            initial.frame,
            MenuFamily.UNIT_ACTION_CHOICES,
            selected_unit=selected,
            selected_item=MenuItem.WAIT,
            actionable=True,
            items=(MenuItem.UNLOAD, MenuItem.WAIT),
        )
        cursor = replace(
            initial.ui.map_cursor,
            status=CursorStatus.AVAILABLE,
            x=0,
            y=0,
        )
        initial = replace(initial, ui=replace(initial.ui, menu=menu, map_cursor=cursor))
        bridge = FakeBridge(initial)
        navigator = ActionNavigator(
            bridge,
            bridge.observe,
            NavigationLimits(
                frame_budget=100,
                poll_frames=1,
                wall_timeout=0.05,
                resolution_wall_timeout=3,
            ),
        )

        if not available:
            with pytest.raises(NavigationError, match="not in the observed Drop targets"):
                await navigator.choose_unload(
                    (3, 3), unit=(1, 1, 23, 0x02022690), width=4, height=4
                )
            assert bridge.keys.count(1) == 1  # Never confirm an unavailable tile.
            return
        result = await navigator.choose_unload(
            (0, 1), unit=(1, 1, 23, 0x02022690), width=4, height=4
        )
        assert result.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
        assert (result.ui.map_cursor.x, result.ui.map_cursor.y) == (0, 1)
        assert bridge.keys == [64, 1, 16, 16, 16, 1]
        assert bridge.gaps[-1] == 20
        assert [event.name for event in navigator.inputs] == [
            "unload-menu-up",
            "begin-unload",
            "drop-next-target",
            "drop-next-target",
            "drop-next-target",
            "confirm-unload-drop",
        ]

    asyncio.run(run())


def test_confirm_yield_moves_left_from_no_to_yes(memory) -> None:
    class FakeBridge:
        def __init__(self, state: GameState) -> None:
            lifecycle = replace(state.lifecycle, phase=LifecyclePhase.BATTLE_ENGINE_UNRESOLVED)
            state = replace(
                state,
                validation=replace(state.validation, lifecycle=lifecycle),
            )
            self.state = replace(
                state,
                ui=replace(
                    state.ui,
                    menu=MenuObservation(
                        state.frame,
                        MenuFamily.CONFIRMATION,
                        selected_item=MenuItem.NO,
                        actionable=True,
                        items=(MenuItem.YES, MenuItem.NO),
                        confirmation_kind="yield",
                    ),
                ),
            )
            self.keys: list[int] = []
            self.neutral_frames = 0

        async def observe(self) -> GameState:
            return self.state

        async def press_keys(self, keys: int, frames: int) -> int:
            self.keys.append(keys)
            selected = self.state.ui.menu.selected_item
            if keys == 32:
                selected = MenuItem.YES
            terminal = keys == 1 and selected is MenuItem.YES
            return self._advance(frames, selected, terminal=terminal)

        async def advance_frames(self, frames: int) -> int:
            self.neutral_frames += frames
            return self._advance(frames, self.state.ui.menu.selected_item)

        def _advance(
            self, frames: int, selected: MenuItem | None, *, terminal: bool = False
        ) -> int:
            frame = self.state.frame + frames
            menu = replace(self.state.ui.menu, frame=frame, selected_item=selected)
            lifecycle = self.state.lifecycle
            battle = self.state.battle
            if terminal:
                lifecycle = replace(
                    lifecycle,
                    phase=LifecyclePhase.RESULT_SEQUENCE,
                    battle_decode_safety=BattleDecodeSafety.BLOCKED,
                )
                battle = ObservedValue(ValueStatus.UNAVAILABLE, None, ("Terminal result",))
            validation = replace(self.state.validation, frame=frame, lifecycle=lifecycle)
            ui = replace(
                self.state.ui,
                frame=frame,
                menu=menu,
                map_cursor=replace(self.state.ui.map_cursor, frame=frame),
            )
            self.state = replace(
                self.state, frame=frame, validation=validation, ui=ui, battle=battle
            )
            return frame

    async def run() -> None:
        state = decode_snapshot(snapshot(memory))
        bridge = FakeBridge(state)
        navigator = ActionNavigator(bridge, bridge.observe)

        terminal = await navigator.confirm_yield()

        assert bridge.keys == [32, 1]
        assert bridge.neutral_frames >= 30
        assert terminal.lifecycle.phase is LifecyclePhase.RESULT_SEQUENCE
        assert terminal.battle.status is ValueStatus.UNAVAILABLE

    asyncio.run(run())


@pytest.mark.parametrize(
    ("targets", "requested", "steps", "available"),
    [
        (((0, 0), (2, 0), (1, 1)), (0, 0), 0, True),
        (((0, 0), (2, 0), (1, 1)), (2, 0), 1, True),
        (((0, 0), (2, 0), (1, 1)), (1, 1), 2, True),
        (((0, 0), (2, 0), (1, 1)), (2, 1), 3, False),
        (((0, 0),), (2, 1), 1, False),
    ],
)
def test_fire_target_navigation_cycles_targets_and_checks_combat_return(
    memory, targets, requested, steps, available
) -> None:
    class FakeBridge:
        def __init__(self, state: GameState) -> None:
            self.state = state
            self.keys: list[int] = []
            self.timeline: list[tuple[str, int]] = []
            self.held: int | None = None
            self.target_index = 0
            self.target_observation_delay = 0
            self.combat_remaining: int | None = None

        async def observe(self) -> GameState:
            if self.state.ui.menu.family is MenuFamily.UNIT_TARGETING:
                await asyncio.sleep(self.target_observation_delay)
            return self.state

        async def press_keys(self, keys: int, frames: int) -> int:
            self.keys.append(keys)
            self.timeline.append(("press", keys))
            if self.held == keys:
                self._update(frames)
                return self.state.frame
            self.held = keys
            family = self.state.ui.menu.family
            if keys == 1 and family is MenuFamily.UNIT_ACTION_CHOICES:
                self._update(frames, family=MenuFamily.UNIT_TARGETING, cursor_position=targets[0])
            elif keys == 1 and family is MenuFamily.UNIT_TARGETING:
                self.combat_remaining = 75
                self._update(frames, family=MenuFamily.UNRESOLVED)
            elif family is MenuFamily.UNIT_ACTION_CHOICES:
                self._update(frames, selected=MenuItem.FIRE)
            else:
                assert keys == 16
                self.target_index = (self.target_index + 1) % len(targets)
                self._update(
                    frames,
                    cursor_position=targets[self.target_index],
                )
            return self.state.frame

        async def advance_frames(self, frames: int) -> int:
            self.timeline.append(("neutral", frames))
            self.held = None
            if self.combat_remaining is not None:
                self.combat_remaining -= frames
                family = (
                    MenuFamily.MAP_INPUT if self.combat_remaining <= 0 else MenuFamily.UNRESOLVED
                )
                self._update(frames, family=family)
            else:
                self._update(frames)
            return self.state.frame

        def _update(
            self,
            frames: int,
            *,
            family: MenuFamily | None = None,
            selected: MenuItem | None = None,
            cursor_position: tuple[int | None, int | None] | None = None,
        ) -> None:
            frame = self.state.frame + frames
            menu = replace(
                self.state.ui.menu,
                frame=frame,
                family=family or self.state.ui.menu.family,
                selected_item=selected or self.state.ui.menu.selected_item,
            )
            cursor = replace(
                self.state.ui.map_cursor,
                frame=frame,
                x=cursor_position[0] if cursor_position is not None else self.state.ui.map_cursor.x,
                y=cursor_position[1] if cursor_position is not None else self.state.ui.map_cursor.y,
                status=CursorStatus.AVAILABLE,
            )
            self.state = replace(
                self.state,
                frame=frame,
                validation=replace(self.state.validation, frame=frame),
                ui=replace(self.state.ui, frame=frame, menu=menu, map_cursor=cursor),
            )

    async def run() -> None:
        initial = decode_snapshot(snapshot(memory))
        selected_unit = SelectedUnitObservation(0x02022690, 1, 1, 1, 1, 1)
        action_menu = MenuObservation(
            initial.frame,
            MenuFamily.UNIT_ACTION_CHOICES,
            selected_unit=selected_unit,
            selected_item=MenuItem.WAIT,
            actionable=True,
            items=(MenuItem.FIRE, MenuItem.WAIT),
        )
        initial = replace(initial, ui=replace(initial.ui, menu=action_menu))
        bridge = FakeBridge(initial)
        navigator = ActionNavigator(
            bridge,
            bridge.observe,
            NavigationLimits(
                frame_budget=40,
                poll_frames=1,
                wall_timeout=0.1,
                resolution_frame_budget=100,
                resolution_wall_timeout=3,
            ),
        )

        state = await navigator.choose_fire()
        assert state.ui.menu.family is MenuFamily.UNIT_TARGETING
        assert [event.name for event in navigator.inputs] == ["fire-menu-up", "confirm-fire"]
        # Two target steps take five observations, exceeding the short watchdog.
        bridge.target_observation_delay = 0.03
        if not available:
            with pytest.raises(NavigationError, match="not an eligible Fire target"):
                await navigator.move_target_cursor_to(*requested, width=3, height=2)
            assert bridge.keys == [64, 1] + [16] * steps
            assert bridge.state.frame < initial.frame + 40
            return
        state = await navigator.move_target_cursor_to(*requested, width=3, height=2)
        assert (state.ui.map_cursor.x, state.ui.map_cursor.y) == requested
        assert [event.name for event in navigator.inputs] == ["target-next"] * steps
        if steps > 1:
            assert bridge.timeline[4:8] == [
                ("neutral", 2),
                ("press", 16),
                ("neutral", 2),
                ("press", 16),
            ]
        state = await navigator.confirm_attack()
        assert state.ui.menu.family is MenuFamily.MAP_INPUT
        assert bridge.keys == [64, 1] + [16] * steps + [1]
        assert bridge.timeline[-3:] == [("neutral", 30)] * 3
        assert [event.name for event in navigator.inputs] == ["confirm-attack-target"]

    asyncio.run(run())


@pytest.mark.parametrize("action", [MenuItem.CAPTURE, MenuItem.WAIT])
def test_unit_action_navigation_returns_to_settled_player_turn(memory, action) -> None:
    async def run() -> None:
        initial = decode_snapshot(snapshot(memory))
        selected = SelectedUnitObservation(0x02022690, 1, 1, 1, 1, 1)
        rows = (MenuItem.FIRE, MenuItem.CAPTURE, MenuItem.WAIT)
        start_item = MenuItem.FIRE if action is MenuItem.WAIT else MenuItem.WAIT
        initial = replace(
            initial,
            ui=replace(
                initial.ui,
                menu=MenuObservation(
                    initial.frame,
                    MenuFamily.UNIT_ACTION_CHOICES,
                    selected_unit=selected,
                    selected_item=start_item,
                    actionable=True,
                    items=rows,
                ),
            ),
        )

        class FakeBridge:
            def __init__(self) -> None:
                self.state = initial
                self.held: int | None = None
                self.keys: list[int] = []

            async def observe(self) -> GameState:
                await asyncio.sleep(0.01)
                return self.state

            async def press_keys(self, keys: int, frames: int) -> int:
                self.keys.append(keys)
                self.held = keys
                selected_item = self.state.ui.menu.selected_item
                if keys == 1:
                    assert selected_item is action
                    family, item = MenuFamily.MAP_INPUT, None
                else:
                    assert keys in (64, 128)
                    index = rows.index(selected_item) + (1 if keys == 128 else -1)
                    family, item = MenuFamily.UNIT_ACTION_CHOICES, rows[index]
                self._update(frames, family=family, selected=item)
                return self.state.frame

            async def advance_frames(self, frames: int) -> int:
                self.held = None
                self._update(frames)
                return self.state.frame

            def _update(self, frames: int, *, family=None, selected=None) -> None:
                frame = self.state.frame + frames
                menu = replace(
                    self.state.ui.menu,
                    frame=frame,
                    family=family or self.state.ui.menu.family,
                    selected_item=selected or self.state.ui.menu.selected_item,
                )
                self.state = replace(
                    self.state,
                    frame=frame,
                    validation=replace(self.state.validation, frame=frame),
                    ui=replace(
                        self.state.ui,
                        frame=frame,
                        map_cursor=replace(self.state.ui.map_cursor, frame=frame),
                        menu=menu,
                    ),
                )

        bridge = FakeBridge()
        navigator = ActionNavigator(
            bridge,
            bridge.observe,
            NavigationLimits(
                frame_budget=40,
                poll_frames=1,
                wall_timeout=0.05,
                resolution_frame_budget=100,
                resolution_wall_timeout=3,
                resolution_poll_frames=10,
            ),
        )
        if action is MenuItem.WAIT:
            result = await navigator.choose_wait()
            assert bridge.keys == [128, 128, 1]
            expected_inputs = ["wait-menu-down", "wait-menu-down", "confirm-wait"]
        else:
            result = await navigator.choose_capture()
            assert bridge.keys == [64, 1]
            expected_inputs = ["capture-menu-up", "confirm-capture"]
        assert result.ui.menu.family is MenuFamily.MAP_INPUT
        assert [event.name for event in navigator.inputs] == expected_inputs

    asyncio.run(run())


@pytest.mark.parametrize(
    ("movement_tile_allowed", "steps"),
    [
        pytest.param(True, 2, id="movement-accepted"),
        pytest.param(False, 2, id="movement-blocked"),
        pytest.param(True, 19, id="backtracking-confirm-fits"),
        pytest.param(True, 20, id="backtracking-confirm-exceeds-budget"),
    ],
)
def test_movement_overlay_checks_route_tiles_before_confirming(
    memory, movement_tile_allowed, steps
) -> None:
    async def run() -> None:
        initial = decode_snapshot(snapshot(memory))
        selected = SelectedUnitObservation(0x02022690, 1, 1, 1, 0, 0)
        cursor = replace(
            initial.ui.map_cursor,
            status=CursorStatus.AVAILABLE,
            x=0,
            y=0,
        )
        initial = replace(
            initial,
            ui=replace(
                initial.ui,
                map_cursor=cursor,
                menu=MenuObservation(
                    initial.frame,
                    MenuFamily.UNIT_MOVEMENT,
                    selected_unit=selected,
                ),
            ),
        )

        class FakeBridge:
            def __init__(self) -> None:
                self.state = initial
                self.keys: list[int] = []
                self.neutral_since_input = 8
                self.animation_remaining = None

            async def observe(self) -> GameState:
                return self.state

            async def press_keys(self, keys: int, frames: int) -> int:
                self.keys.append(keys)
                if keys == 16 and movement_tile_allowed and self.neutral_since_input >= 8:
                    self._update(frames, cursor=(1, 0))
                elif keys == 32 and movement_tile_allowed and self.neutral_since_input >= 8:
                    self._update(frames, cursor=(0, 0))
                elif keys == 128 and movement_tile_allowed and self.neutral_since_input >= 8:
                    self._update(frames, cursor=(1, 1))
                elif keys == 1:
                    # The accepted route animates beyond both ordinary input
                    # limits; it must use the separate resolution allowance.
                    await asyncio.sleep(0.02)
                    self.animation_remaining = 50
                    self._update(frames, menu=MenuFamily.UNIT_ACTION)
                else:
                    self._update(frames)
                self.neutral_since_input = 0
                return self.state.frame

            async def advance_frames(self, frames: int) -> int:
                self.neutral_since_input += frames
                menu = None
                if self.animation_remaining is not None:
                    self.animation_remaining -= frames
                    if self.animation_remaining <= 0:
                        menu = MenuFamily.UNIT_ACTION_CHOICES
                self._update(frames, menu=menu)
                return self.state.frame

            def _update(self, frames: int, *, cursor=None, menu=None) -> None:
                frame = self.state.frame + frames
                current_cursor = replace(
                    self.state.ui.map_cursor,
                    frame=frame,
                    x=cursor[0] if cursor is not None else self.state.ui.map_cursor.x,
                    y=cursor[1] if cursor is not None else self.state.ui.map_cursor.y,
                )
                current_menu = replace(
                    self.state.ui.menu,
                    frame=frame,
                    family=menu or self.state.ui.menu.family,
                    selected_unit=selected,
                    actionable=True if menu is not None else self.state.ui.menu.actionable,
                )
                self.state = replace(
                    self.state,
                    frame=frame,
                    validation=replace(self.state.validation, frame=frame),
                    ui=replace(
                        self.state.ui,
                        frame=frame,
                        map_cursor=current_cursor,
                        menu=current_menu,
                    ),
                )

        bridge = FakeBridge()
        navigator = ActionNavigator(
            bridge,
            bridge.observe,
            NavigationLimits(
                frame_budget=32 if steps == 2 else 180,
                poll_frames=1,
                wall_timeout=0.01,
                resolution_frame_budget=6000,
                resolution_poll_frames=1,
                resolution_wall_timeout=1,
            ),
        )
        unit_identity = (1, 1, 1, selected.record_address)
        route = ((1, 0), (1, 1)) if steps == 2 else tuple((1 - i % 2, 0) for i in range(steps))
        if steps == 20:
            with pytest.raises(NavigationError, match="Navigation frame budget exhausted") as error:
                await navigator.move_selected_unit_along_path(
                    route, unit=unit_identity, width=2, height=2
                )
            assert len(error.value.context.input_sequence) == steps
            assert 1 not in bridge.keys
            return
        if movement_tile_allowed:
            result = await navigator.move_selected_unit_along_path(
                route, unit=unit_identity, width=2, height=2
            )
            assert result.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
            assert bridge.keys == ([16, 128, 1] if steps == 2 else [16, 32] * 9 + [16, 1])
        else:
            with pytest.raises(NavigationError, match="Timed out waiting"):
                await navigator.move_selected_unit_along_path(
                    ((1, 0), (1, 1)), unit=unit_identity, width=2, height=2
                )
            assert 1 not in bridge.keys

    asyncio.run(run())


@pytest.mark.parametrize(
    ("action", "initial_row", "expected_keys"),
    [
        (MenuItem.WAIT, 0, [128, 128, 1]),
        (MenuItem.FIRE, 2, [64, 64, 1]),
        (MenuItem.CAPTURE, 0, [128, 1]),
    ],
)
def test_three_row_unit_actions_verify_intermediate_selection(
    memory, action, initial_row, expected_keys
):
    async def check():
        state = decode_snapshot(snapshot(memory))
        selected = SelectedUnitObservation(0x02022690, 1, 1, 1, 1, 1)
        rows = (MenuItem.FIRE, MenuItem.CAPTURE, MenuItem.WAIT)
        state = replace(
            state,
            ui=replace(
                state.ui,
                menu=MenuObservation(
                    state.frame,
                    MenuFamily.UNIT_ACTION_CHOICES,
                    selected,
                    selected_item=rows[initial_row],
                    actionable=True,
                    items=rows,
                ),
            ),
        )
        keys_seen = []

        class Bridge:
            async def advance_frames(self, frames):
                nonlocal state
                frame = state.frame + frames
                state = replace(
                    state,
                    frame=frame,
                    validation=replace(state.validation, frame=frame),
                    ui=replace(
                        state.ui,
                        frame=frame,
                        menu=replace(state.ui.menu, frame=frame),
                        map_cursor=replace(state.ui.map_cursor, frame=frame),
                    ),
                )
                return frame

            async def press_keys(self, keys, frames):
                nonlocal state
                keys_seen.append(keys)
                menu = state.ui.menu
                if keys == 1:
                    assert menu.selected_item is action
                    family = (
                        MenuFamily.UNIT_TARGETING
                        if action is MenuItem.FIRE
                        else MenuFamily.MAP_INPUT
                    )
                    menu = MenuObservation(
                        state.frame, family, selected if action is MenuItem.FIRE else None
                    )
                else:
                    index = rows.index(menu.selected_item) + (1 if keys == 128 else -1)
                    menu = replace(menu, selected_item=rows[index])
                state = replace(state, ui=replace(state.ui, menu=menu))
                return await self.advance_frames(frames)

        async def observe():
            return state

        navigator = ActionNavigator(Bridge(), observe)
        await {
            MenuItem.WAIT: navigator.choose_wait,
            MenuItem.FIRE: navigator.choose_fire,
            MenuItem.CAPTURE: navigator.choose_capture,
        }[action]()
        assert keys_seen == expected_keys

    asyncio.run(check())
