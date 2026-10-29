"""ROM-independent validation for bounded action navigation."""

import asyncio
from dataclasses import replace

import pytest
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.action_navigation import ActionNavigator, NavigationLimits, validate_path
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import GameState
from aw2_lab.ui_state import MenuFamily, MenuItem, MenuObservation


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


def test_navigate_menu_tracks_each_verified_command_row(memory) -> None:
    class FakeBridge:
        def __init__(self, state: GameState) -> None:
            self.state = state
            self.keys: list[int] = []

        async def observe(self) -> GameState:
            return self.state

        async def press_keys(self, keys: int, frames: int) -> int:
            self.keys.append(keys)
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
        assert bridge.keys == [128, 1, 128, 128, 2, 128, 1, 128, 128, 128]
        assert [event.name for event in navigator.inputs] == [
            "menu-back-to-command",
            "menu-down",
            "open-options-submenu",
            "menu-down",
            "menu-down",
            "menu-down",
        ]

    asyncio.run(run())
