"""Bounded controller navigation over the currently recognized battle UI."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_observation import MatchObservation
from aw2_lab.state_model import GameState, ValueStatus
from aw2_lab.ui_state import CursorStatus, MenuFamily, MenuItem

_KEY_A = 1
_KEY_B = 2
_KEY_RIGHT = 16
_KEY_LEFT = 32
_KEY_UP = 64
_KEY_DOWN = 128


@dataclass(frozen=True, slots=True)
class NavigationLimits:
    """Hard limits for one navigation operation."""

    frame_budget: int = 180
    poll_frames: int = 10
    wall_timeout: float = 15.0
    input_frames: int = 1
    input_gap_frames: int = 2
    resolution_frame_budget: int = 6000
    resolution_wall_timeout: float = 60.0
    resolution_poll_frames: int = 30

    def __post_init__(self) -> None:
        if not 1 <= self.frame_budget <= 36_000 or not 1 <= self.poll_frames <= 600:
            raise ValueError("frame budget must be 1..36000 and poll interval must be 1..600")
        if (
            not 1 <= self.input_frames <= 600
            or not 1 <= self.input_gap_frames <= 60
            or not 1 <= self.resolution_frame_budget <= 36_000
            or not 1 <= self.resolution_poll_frames <= 600
            or not math.isfinite(self.wall_timeout)
            or self.wall_timeout <= 0
            or not math.isfinite(self.resolution_wall_timeout)
            or self.resolution_wall_timeout <= 0
        ):
            raise ValueError(
                "input frame count and finite wall timeout must be positive and bounded"
            )


@dataclass(frozen=True, slots=True)
class InputEvent:
    name: str
    keys: int
    frames: int
    start_frame: int
    end_frame: int


@dataclass(frozen=True, slots=True)
class NavigationFailureContext:
    operation: str
    phase: str
    frame: int
    input_sequence: tuple[InputEvent, ...]
    screenshot: str | None = None


class NavigationError(RuntimeError):
    """Navigation stopped because an observed precondition or bound failed."""

    def __init__(self, message: str, context: NavigationFailureContext) -> None:
        super().__init__(message)
        self.context = context


StateObserver = Callable[[], Awaitable[GameState]]
ScreenshotWriter = Callable[[Path], Awaitable[Path]]
Postcondition = Callable[[GameState], bool]


def validate_path(
    path: Sequence[tuple[int, int]], *, start: tuple[int, int], width: int, height: int
) -> tuple[tuple[int, int], ...]:
    """Validate route shape only; AW2 remains authoritative about terrain legality."""
    if width < 1 or height < 1:
        raise ValueError("map dimensions must be positive")
    if (
        not isinstance(start, (tuple, list))
        or len(start) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in start)
    ):
        raise ValueError("start coordinate must be an integer pair")
    if not 0 <= start[0] < width or not 0 <= start[1] < height:
        raise ValueError("start coordinate is outside the map")
    points = tuple(path)
    previous = start
    for point in points:
        if (
            not isinstance(point, (tuple, list))
            or len(point) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in point)
        ):
            raise ValueError("path coordinates must be integer pairs")
        x, y = point
        if not 0 <= x < width or not 0 <= y < height:
            raise ValueError("path coordinate is outside the map")
        if abs(x - previous[0]) + abs(y - previous[1]) != 1:
            raise ValueError("each path step must be adjacent to the previous coordinate")
        previous = point
    return points


@dataclass(slots=True)
class ActionNavigator:
    """Perform input-only navigation and verify each transition from GameState."""

    bridge: LuaBridgeClient
    observe: StateObserver
    limits: NavigationLimits = field(default_factory=NavigationLimits)
    screenshot_writer: ScreenshotWriter | None = None
    screenshot_directory: Path | None = None
    inputs: list[InputEvent] = field(default_factory=list, init=False)
    _frames_used: int = field(default=0, init=False)
    _last_state: GameState | None = field(default=None, init=False)
    _operation: str = field(default="navigation", init=False)

    async def move_cursor_to(self, x: int, y: int) -> GameState:
        """Move over map-input UI, checking the exact cursor delta after every tap."""
        async with self._bounded_operation():
            self._begin("move_cursor")
            return await self._move_cursor(x, y)

    async def _move_cursor(self, x: int, y: int) -> GameState:
        state = await self._observe()
        cursor = state.ui.map_cursor
        if (
            state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or state.ui.menu.family is not MenuFamily.MAP_INPUT
            or cursor.status is not CursorStatus.AVAILABLE
            or cursor.x is None
            or cursor.y is None
        ):
            raise await self._fail("Map cursor movement requires recognized map input", state)
        battle = state.battle.value
        if state.battle.status is not ValueStatus.AVAILABLE or battle is None:
            raise await self._fail("Validated map dimensions are unavailable", state)
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, int)
            or not isinstance(y, int)
        ):
            raise await self._fail("Destination must use integer coordinates", state)
        if not (0 <= x < battle.map.width and 0 <= y < battle.map.height):
            raise await self._fail("Destination is outside the validated map", state)
        while (cursor.x, cursor.y) != (x, y):
            dx, dy = x - cursor.x, y - cursor.y
            if dx:
                name, sx, sy, key = (
                    ("right", 1, 0, _KEY_RIGHT) if dx > 0 else ("left", -1, 0, _KEY_LEFT)
                )
            else:
                name, sx, sy, key = ("down", 0, 1, _KEY_DOWN) if dy > 0 else ("up", 0, -1, _KEY_UP)
            expected = (cursor.x + sx, cursor.y + sy)
            await self._tap(name, key)

            def cursor_matches(
                value: GameState,
                expected_position: tuple[int | None, int | None] = expected,
            ) -> bool:
                return (
                    value.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
                    and value.ui.menu.family is MenuFamily.MAP_INPUT
                    and value.ui.map_cursor.status is CursorStatus.AVAILABLE
                    and (value.ui.map_cursor.x, value.ui.map_cursor.y) == expected_position
                )

            state = await self._wait_for(
                cursor_matches,
                description=f"cursor to reach {expected}",
            )
            cursor = state.ui.map_cursor
        return state

    async def select_unit(self, unit_id: str, observation: MatchObservation) -> GameState:
        """Select an active, unused current-player unit by its lifetime identity."""
        async with self._bounded_operation():
            self._begin("select_unit")
            battle = observation.game_state.battle.value
            if battle is None or observation.identity_status.value != "available":
                state = await self._observe()
                raise await self._fail("Unit identity or battle state is unavailable", state)
            matches = [
                identity
                for identity in observation.unit_identities
                if identity.identity_id == unit_id
            ]
            if len(matches) != 1:
                state = await self._observe()
                raise await self._fail("Unit ID is not present in this observation", state)
            unit = next(
                (item for item in battle.units if item.reference == matches[0].reference), None
            )
            if unit is None or unit.army_slot != battle.active_player_slot or unit.used_this_turn:
                state = await self._observe()
                raise await self._fail(
                    "Unit is unavailable for selection on the active turn", state
                )
            state = await self._move_cursor(unit.x, unit.y)
            live_battle = state.battle.value
            live_unit = (
                next((item for item in live_battle.units if item.reference == unit.reference), None)
                if live_battle is not None
                else None
            )
            if (
                state.battle.status is not ValueStatus.AVAILABLE
                or live_battle is None
                or live_battle.active_player_slot != unit.army_slot
                or live_unit is None
                or live_unit.unit_type != unit.unit_type
                or live_unit.x != unit.x
                or live_unit.y != unit.y
                or live_unit.used_this_turn
            ):
                raise await self._fail(
                    "Selected unit changed since the committed observation", state
                )
            await self._tap("select-unit", _KEY_A)
            state = await self._wait_for(
                lambda value: (
                    value.ui.menu.family is MenuFamily.UNIT_MOVEMENT
                    and value.ui.menu.selected_unit is not None
                    and (
                        value.ui.menu.selected_unit.army_slot,
                        value.ui.menu.selected_unit.unit_slot,
                        value.ui.menu.selected_unit.unit_type,
                        value.ui.menu.selected_unit.x,
                        value.ui.menu.selected_unit.y,
                    )
                    == (unit.army_slot, unit.unit_slot, unit.unit_type, unit.x, unit.y)
                ),
                description="the requested unit action menu",
            )
            return state

    async def move_selected_unit_along_path(
        self,
        path: Sequence[tuple[int, int]],
        *,
        unit: tuple[int, int, int, int],
        width: int,
        height: int,
    ) -> GameState:
        """Move a selected unit along an explicit adjacent route and open action choices."""
        async with self._bounded_operation():
            self._begin("move_unit")
            state = await self._observe()
            selected = state.ui.menu.selected_unit
            cursor = state.ui.map_cursor
            if (
                state.ui.menu.family is not MenuFamily.UNIT_MOVEMENT
                or selected is None
                or (
                    selected.army_slot,
                    selected.unit_slot,
                    selected.unit_type,
                    selected.record_address,
                )
                != unit
                or cursor.status is not CursorStatus.AVAILABLE
                or cursor.x is None
                or cursor.y is None
            ):
                raise await self._fail("Movement requires the requested selected unit", state)
            route = validate_path(
                path,
                start=(cursor.x, cursor.y),
                width=width,
                height=height,
            )
            for x, y in route:
                dx, dy = x - cursor.x, y - cursor.y
                name, key = (
                    ("right", _KEY_RIGHT)
                    if dx == 1
                    else ("left", _KEY_LEFT)
                    if dx == -1
                    else ("down", _KEY_DOWN)
                    if dy == 1
                    else ("up", _KEY_UP)
                )
                await self._tap(f"move-{name}", key)

                def moved(
                    value: GameState,
                    position: tuple[int, int] = (x, y),
                    expected_unit: tuple[int, int, int, int] = unit,
                ) -> bool:
                    current = value.ui.menu.selected_unit
                    return (
                        value.ui.menu.family is MenuFamily.UNIT_MOVEMENT
                        and value.ui.map_cursor.status is CursorStatus.AVAILABLE
                        and (value.ui.map_cursor.x, value.ui.map_cursor.y) == position
                        and current is not None
                        and (
                            current.army_slot,
                            current.unit_slot,
                            current.unit_type,
                            current.record_address,
                        )
                        == expected_unit
                    )

                state = await self._wait_for(
                    moved, description=f"movement cursor to reach {(x, y)}"
                )
                cursor = state.ui.map_cursor
            await self._tap("accept-movement-destination", _KEY_A)
            return await self._wait_for(
                lambda value: (
                    value.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
                    and value.ui.menu.selected_unit is not None
                    and (
                        value.ui.menu.selected_unit.army_slot,
                        value.ui.menu.selected_unit.unit_slot,
                        value.ui.menu.selected_unit.unit_type,
                        value.ui.menu.selected_unit.record_address,
                    )
                    == unit
                    and value.ui.menu.actionable is True
                ),
                description="the selected unit's recognized action choices",
            )

    async def choose_wait(self) -> GameState:
        """Choose the explicitly recognized Wait row and require a settled player turn."""
        async with self._bounded_operation():
            self._begin("choose_wait")
            state = await self._observe()
            menu = state.ui.menu
            if (
                menu.family is not MenuFamily.UNIT_ACTION_CHOICES
                or menu.selected_item is None
                or MenuItem.WAIT not in menu.items
                or not menu.actionable
            ):
                raise await self._fail("Wait requires a recognized unit action selector", state)
            delta = menu.items.index(MenuItem.WAIT) - menu.items.index(menu.selected_item)
            if delta:
                key, name = (_KEY_DOWN, "down") if delta > 0 else (_KEY_UP, "up")
                for _ in range(abs(delta)):
                    await self._tap(f"wait-menu-{name}", key)
                    state = await self._wait_for(
                        lambda value: (
                            value.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
                            and value.ui.menu.selected_item is MenuItem.WAIT
                            and value.ui.menu.selected_unit == menu.selected_unit
                        ),
                        description="Wait selected in the action menu",
                    )
            await self._tap("confirm-wait", _KEY_A)
            return await self._wait_for(
                lambda value: (
                    value.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
                    and value.ui.menu.family is MenuFamily.MAP_INPUT
                    and value.battle.status is ValueStatus.AVAILABLE
                ),
                description="the settled player-turn boundary after Wait",
            )

    async def choose_capture(self) -> GameState:
        """Choose Capture and wait for the settled turn or a recognized battle result."""
        async with self._bounded_operation(timeout=self.limits.resolution_wall_timeout):
            self._begin("resolve_capture")
            state = await self._observe()
            menu = state.ui.menu
            if (
                menu.family is not MenuFamily.UNIT_ACTION_CHOICES
                or menu.selected_item is None
                or MenuItem.CAPTURE not in menu.items
                or not menu.actionable
            ):
                raise await self._fail("Capture requires a recognized unit action selector", state)
            delta = menu.items.index(MenuItem.CAPTURE) - menu.items.index(menu.selected_item)
            if delta:
                key, name = (_KEY_DOWN, "down") if delta > 0 else (_KEY_UP, "up")
                for _ in range(abs(delta)):
                    await self._tap(f"capture-menu-{name}", key)
                    state = await self._wait_for(
                        lambda value: (
                            value.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
                            and value.ui.menu.selected_item is MenuItem.CAPTURE
                            and value.ui.menu.selected_unit == menu.selected_unit
                        ),
                        description="Capture selected in the action menu",
                    )
            await self._tap("confirm-capture", _KEY_A)
            terminal_phases = {
                LifecyclePhase.RESULT_SEQUENCE,
                LifecyclePhase.VICTORY_PRESENTATION,
                LifecyclePhase.DEFEAT_PRESENTATION,
                LifecyclePhase.RESULT_SUMMARY,
                LifecyclePhase.SAVE_PROGRESS_PROMPT,
            }
            return await self._wait_for(
                lambda value: (
                    (
                        value.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
                        and value.ui.menu.family is MenuFamily.MAP_INPUT
                        and value.battle.status is ValueStatus.AVAILABLE
                    )
                    or value.lifecycle.phase in terminal_phases
                ),
                description="post-capture control or a recognized match result",
                frame_budget=self.limits.resolution_frame_budget,
                poll_frames=self.limits.resolution_poll_frames,
            )

    async def choose_fire(self) -> GameState:
        """Choose Fire from a recognized unit selector and require Fire target mode."""
        async with self._bounded_operation():
            self._begin("choose_fire")
            state = await self._observe()
            menu = state.ui.menu
            if (
                menu.family is not MenuFamily.UNIT_ACTION_CHOICES
                or menu.selected_item is None
                or MenuItem.FIRE not in menu.items
                or not menu.actionable
            ):
                raise await self._fail("Fire requires a recognized unit action selector", state)
            delta = menu.items.index(MenuItem.FIRE) - menu.items.index(menu.selected_item)
            if delta:
                key, name = (_KEY_DOWN, "down") if delta > 0 else (_KEY_UP, "up")
                for _ in range(abs(delta)):
                    await self._tap(f"fire-menu-{name}", key)
                    state = await self._wait_for(
                        lambda value: (
                            value.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
                            and value.ui.menu.selected_item is MenuItem.FIRE
                            and value.ui.menu.selected_unit == menu.selected_unit
                        ),
                        description="Fire selected in the action menu",
                    )
            await self._tap("confirm-fire", _KEY_A)
            return await self._wait_for(
                lambda value: (
                    value.ui.menu.family is MenuFamily.UNIT_TARGETING
                    and value.ui.menu.selected_unit == menu.selected_unit
                    and value.ui.map_cursor.status is CursorStatus.AVAILABLE
                ),
                description="the recognized Fire target cursor",
            )

    async def move_target_cursor_to(self, x: int, y: int, *, width: int, height: int) -> GameState:
        """Cycle AW2's eligible Fire targets until the requested tile is selected."""
        async with self._bounded_operation():
            self._begin("move_attack_target")
            state = await self._observe()
            cursor = state.ui.map_cursor
            if (
                state.ui.menu.family is not MenuFamily.UNIT_TARGETING
                or state.ui.menu.selected_unit is None
                or cursor.status is not CursorStatus.AVAILABLE
                or cursor.x is None
                or cursor.y is None
            ):
                raise await self._fail("Target movement requires recognized Fire targeting", state)
            if (
                isinstance(x, bool)
                or isinstance(y, bool)
                or not isinstance(x, int)
                or not isinstance(y, int)
                or not 0 <= x < width
                or not 0 <= y < height
            ):
                raise await self._fail("Attack target is outside the validated map", state)
            selected_unit = state.ui.menu.selected_unit
            visited: set[tuple[int | None, int | None]] = set()
            while (cursor.x, cursor.y) != (x, y):
                position = (cursor.x, cursor.y)
                if position in visited:
                    raise await self._fail("Requested tile is not an eligible Fire target", state)
                visited.add(position)
                await self._tap("target-next", _KEY_RIGHT)

                def target_cursor_ready(value: GameState) -> bool:
                    return (
                        value.ui.menu.family is MenuFamily.UNIT_TARGETING
                        and value.ui.menu.selected_unit == selected_unit
                        and value.ui.map_cursor.status is CursorStatus.AVAILABLE
                        and value.ui.map_cursor.x is not None
                        and value.ui.map_cursor.y is not None
                    )

                state = await self._wait_for(
                    target_cursor_ready,
                    description="the next eligible Fire target",
                )
                cursor = state.ui.map_cursor
            return state

    async def confirm_attack(self) -> GameState:
        """Confirm the selected tile and wait through combat to a stable outcome."""
        async with self._bounded_operation(timeout=self.limits.resolution_wall_timeout):
            self._begin("resolve_attack")
            state = await self._observe()
            if (
                state.ui.menu.family is not MenuFamily.UNIT_TARGETING
                or state.ui.menu.selected_unit is None
                or state.ui.map_cursor.status is not CursorStatus.AVAILABLE
            ):
                raise await self._fail("Attack confirmation requires a verified target tile", state)
            await self._tap("confirm-attack-target", _KEY_A)
            terminal_phases = {
                LifecyclePhase.RESULT_SEQUENCE,
                LifecyclePhase.VICTORY_PRESENTATION,
                LifecyclePhase.DEFEAT_PRESENTATION,
                LifecyclePhase.RESULT_SUMMARY,
                LifecyclePhase.SAVE_PROGRESS_PROMPT,
            }
            return await self._wait_for(
                lambda value: (
                    (
                        value.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
                        and value.ui.menu.family is MenuFamily.MAP_INPUT
                        and value.battle.status is ValueStatus.AVAILABLE
                    )
                    or value.lifecycle.phase in terminal_phases
                ),
                description="post-combat control or a recognized match result",
                frame_budget=self.limits.resolution_frame_budget,
                poll_frames=self.limits.resolution_poll_frames,
            )

    async def navigate_menu(self, item: MenuItem) -> GameState:
        """Navigate the known battle-menu hierarchy to ``item`` from a recognized selector."""
        async with self._bounded_operation():
            self._begin("navigate_menu")
            state = await self._observe()
            item_family = self._menu_family_for_item(item)
            if item_family is None:
                raise await self._fail(f"No recognized selector contains {item.value}", state)
            if (
                state.ui.menu.family
                not in (
                    MenuFamily.COMMAND,
                    MenuFamily.INTEL,
                    MenuFamily.OPTIONS,
                )
                or state.ui.menu.selected_item is None
            ):
                raise await self._fail(
                    "Menu navigation requires a recognized battle selector and current selection",
                    state,
                )

            if state.ui.menu.family is not item_family:
                if state.ui.menu.family is not MenuFamily.COMMAND:
                    await self._tap("menu-back-to-command", _KEY_B)
                    state = await self._wait_for(
                        lambda value: (
                            value.ui.menu.family is MenuFamily.COMMAND
                            and value.ui.menu.selected_item is not None
                        ),
                        description="the command selector after closing a submenu",
                    )

                if item_family is not MenuFamily.COMMAND:
                    parent = self._parent_item_for_family(item_family)
                    if parent is None:
                        raise await self._fail(
                            "No recognized parent menu opens this selector", state
                        )
                    state = await self._navigate_selector(parent, MenuFamily.COMMAND, state)
                    await self._tap(f"open-{item_family.value}-submenu", _KEY_A)
                    state = await self._wait_for(
                        lambda value: (
                            value.ui.menu.family is item_family
                            and value.ui.menu.selected_item is not None
                            and value.ui.menu.actionable is True
                        ),
                        description=f"the {item_family.value} submenu",
                    )

            return await self._navigate_selector(item, item_family, state)

    async def _navigate_selector(
        self, item: MenuItem, family: MenuFamily, state: GameState
    ) -> GameState:
        """Move within one currently observed selector without changing menus."""
        from aw2_lab.ui_state import _MENU_ITEMS

        rows = _MENU_ITEMS.get(family.value)
        selected = state.ui.menu.selected_item
        if rows is None or selected not in rows or item not in rows:
            raise await self._fail("Requested item is not in the current selector", state)
        delta = rows.index(item) - rows.index(selected)
        key, name = (_KEY_DOWN, "down") if delta > 0 else (_KEY_UP, "up")
        for _ in range(abs(delta)):
            current = state.ui.menu.selected_item
            if current not in rows:
                raise await self._fail("Selector changed during menu navigation", state)
            next_index = rows.index(current) + (1 if delta > 0 else -1)
            expected = rows[next_index]
            await self._tap(f"menu-{name}", key)

            def selection_matches(value: GameState, expected: MenuItem = expected) -> bool:
                return value.ui.menu.family is family and value.ui.menu.selected_item is expected

            state = await self._wait_for(
                selection_matches,
                description=f"menu selection {expected.value}",
            )
        return state

    @staticmethod
    def _menu_family_for_item(item: MenuItem) -> MenuFamily | None:
        from aw2_lab.ui_state import _MENU_ITEMS

        return next(
            (MenuFamily(family) for family, rows in _MENU_ITEMS.items() if item in rows), None
        )

    @staticmethod
    def _parent_item_for_family(family: MenuFamily) -> MenuItem | None:
        return {
            MenuFamily.INTEL: MenuItem.INTEL,
            MenuFamily.OPTIONS: MenuItem.OPTIONS,
        }.get(family)

    async def confirm(self, postcondition: Postcondition, *, label: str) -> GameState:
        """Confirm an actionable menu choice and require its caller-defined result.

        The postcondition can recognize an opened submenu; callers then use
        ``navigate_menu`` with that submenu's observed family.
        """
        async with self._bounded_operation():
            self._begin("confirm")
            state = await self._observe()
            if (
                state.ui.menu.family in (MenuFamily.UNRESOLVED, MenuFamily.MAP_INPUT)
                or not state.ui.menu.actionable
            ):
                raise await self._fail("Confirmation requires a recognized actionable menu", state)
            await self._tap(f"confirm-{label}", _KEY_A)
            return await self._wait_for(postcondition, description=f"postcondition {label}")

    def _begin(self, operation: str) -> None:
        self._operation, self._frames_used = operation, 0
        self.inputs.clear()

    @asynccontextmanager
    async def _bounded_operation(self, *, timeout: float | None = None) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(timeout or self.limits.wall_timeout):
                yield
        except TimeoutError as error:
            state = self._last_state
            if state is None:
                state = await self._observe()
            raise await self._fail("Navigation wall-clock watchdog expired", state) from error

    async def _observe(self) -> GameState:
        state = await self.observe()
        self._last_state = state
        return state

    async def _tap(self, name: str, keys: int) -> None:
        count = self.limits.input_frames
        # Let cursor changes and new selectors settle before dispatching A.
        # Sampling release also makes consecutive button presses distinct.
        gap = self.limits.input_gap_frames
        if self._frames_used + gap + count > self.limits.frame_budget:
            state = await self._observe()
            raise await self._fail("Navigation frame budget exhausted", state)
        end = await self.bridge.advance_frames(gap)
        self._frames_used += gap
        state = await self._observe()
        if state.frame != end:
            raise await self._fail("Observed state frame does not match release gap", state)
        start = self._last_state.frame if self._last_state is not None else 0
        end = await self.bridge.press_keys(keys, count)
        self.inputs.append(InputEvent(name, keys, count, start, end))
        self._frames_used += count
        state = await self._observe()
        if state.frame != end:
            raise await self._fail("Observed state frame does not match input completion", state)

    async def _wait_for(
        self,
        predicate: Postcondition,
        *,
        description: str,
        frame_budget: int | None = None,
        poll_frames: int | None = None,
    ) -> GameState:
        budget = self.limits.frame_budget if frame_budget is None else frame_budget
        interval = self.limits.poll_frames if poll_frames is None else poll_frames
        state = self._last_state
        if state is None:
            state = await self._observe()
        while True:
            if predicate(state):
                return state
            if self._frames_used + interval > budget:
                raise await self._fail(
                    f"Timed out waiting for {description} within frame budget", state
                )
            end = await self.bridge.advance_frames(interval)
            self._frames_used += interval
            state = await self._observe()
            if state.frame != end:
                raise await self._fail("Observed state frame does not match polling frame", state)

    async def _fail(self, message: str, state: GameState) -> NavigationError:
        screenshot: str | None = None
        if self.screenshot_writer is not None and self.screenshot_directory is not None:
            try:
                self.screenshot_directory.mkdir(parents=True, exist_ok=True)
                path = self.screenshot_directory / f"{self._operation}-frame-{state.frame}.png"
                screenshot = str(await self.screenshot_writer(path))
            except OSError, RuntimeError, TimeoutError, ValueError:
                screenshot = None
        return NavigationError(
            message,
            NavigationFailureContext(
                self._operation,
                state.lifecycle.phase.value,
                state.frame,
                tuple(self.inputs),
                screenshot,
            ),
        )
