"""Typed UI observations for the verified Versus battle context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aw2_lab.lifecycle import (
    BattleControlObservation,
    LifecycleAssessment,
    LifecycleEngine,
    LifecyclePhase,
)
from aw2_lab.state_validation import (
    ARMY_STRIDE,
    MAP_BASE,
    UNIT_BASE,
    UNIT_STRIDE,
    UNIT_TYPES,
    UNITS_PER_ARMY,
    BattleMemorySnapshot,
    BattleValidationReport,
    ValidationStatus,
)

CURSOR_SOURCE = 0x030033E4
CURSOR_CACHE = 0x03003140
CURRENT_UNIT_POINTER = 0x030040D8
ACTIVE_PLAYER = 0x030033EC
UNIT_ACTION_MENU_SCRIPT = 0x0849BE38
SCREEN_PROCESS_POOL = 0x0200D610
SCREEN_PROCESS_STRIDE = 0x6C
SCREEN_PROCESS_COUNT = 32
SELECTOR_OBJECT = 0x03001470
SELECTOR_TABLE = 0x03001490
SELECTOR_ROW_COUNT = 0x030014B1
SELECTOR_SELECTED_ROW = 0x030014B2
SELECTOR_ITEM_IDS = 0x030014A1
CONTROLLER_STATE = 0x030032D8
CONTROLLER_LOCK = 0x030030F0
MAP_ID = 0x03003FC2
UNIT_MOVEMENT_SELECTOR = 0x08499B4C
# This process shares the selector's storage. Offset +0x20 is a cursor
# graphics loading counter here, not a menu table pointer; it saturates at 8.
CURSOR_GRAPHICS_PROGRESS = 0x03001490
UNIT_ACTION_SELECTOR = 0x0848A42C
UNIT_ACTION_TABLE = 0x0849AE28
FIRE_TARGETING_SCRIPT = 0x0849A9F8

# Original-ROM table signatures for the three selectors verified in the
# supplied Versus battle checkpoints. Each item ID has a non-null A callback.
# Eligibility is checked against the current map's original-ROM header.
_MENU_TABLES = {
    0x0849AAC0: ("command", 5, (0, 1, 4, 5, 6)),
    0x0849ABC0: ("intel", 3, (0, 2, 3)),
    0x0849AC60: ("options", 5, (0, 1, 2, 7, 8)),
}


class CursorStatus(StrEnum):
    """Whether the observed map cursor can be reported for this frame."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MapCursorObservation:
    """Map cursor coordinates, distinct from menu selection and input readiness."""

    frame: int
    status: CursorStatus
    x: int | None = None
    y: int | None = None
    reasons: tuple[str, ...] = ()


class MenuFamily(StrEnum):
    """Menu contexts supported by the current UI research subset."""

    MAP_INPUT = "map_input"
    COMMAND = "command"
    INTEL = "intel"
    OPTIONS = "options"
    UNIT_ACTION = "unit_action"
    UNIT_MOVEMENT = "unit_movement"
    UNIT_ACTION_CHOICES = "unit_action_choices"
    UNIT_TARGETING = "unit_targeting"
    UNRESOLVED = "unresolved"


class MenuItem(StrEnum):
    """Choices resolved from the verified general battle selectors."""

    CO = "co"
    INTEL = "intel"
    OPTIONS = "options"
    SAVE = "save"
    END = "end"
    STATUS = "status"
    UNIT = "unit"
    RULES = "rules"
    DELETE = "delete"
    YIELD = "yield"
    MUSIC = "music"
    VISUAL_MODE = "visual_mode"
    EXIT_MAP = "exit_map"
    FIRE = "fire"
    CAPTURE = "capture"
    WAIT = "wait"
    OTHER_UNIT_ACTION = "other_unit_action"


_MENU_ITEMS = {
    "command": (MenuItem.CO, MenuItem.INTEL, MenuItem.OPTIONS, MenuItem.SAVE, MenuItem.END),
    "intel": (MenuItem.STATUS, MenuItem.UNIT, MenuItem.RULES),
    "options": (
        MenuItem.DELETE,
        MenuItem.YIELD,
        MenuItem.MUSIC,
        MenuItem.VISUAL_MODE,
        MenuItem.EXIT_MAP,
    ),
}


@dataclass(frozen=True, slots=True)
class SelectedUnitObservation:
    """A unit record resolved in a verified unit-action menu context."""

    record_address: int
    army_slot: int
    unit_slot: int
    unit_type: int
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class MenuObservation:
    """Recognized menu context and its current typed selection, when known."""

    frame: int
    family: MenuFamily
    selected_unit: SelectedUnitObservation | None = None
    reasons: tuple[str, ...] = ()
    selected_item: MenuItem | None = None
    actionable: bool | None = None
    unrecognized: UnrecognizedUIState | None = None
    items: tuple[MenuItem, ...] = ()


@dataclass(frozen=True, slots=True)
class UnrecognizedUIState:
    """Raw classification evidence retained when no supported UI family fits."""

    frame: int
    lifecycle: LifecycleAssessment
    controller: BattleControlObservation
    selector_object: int
    selector_table: int
    reason: str


def observe_map_cursor(
    snapshot: BattleMemorySnapshot, validation: BattleValidationReport
) -> MapCursorObservation:
    """Expose map cursor coordinates only in a validated, settled player turn.

    The source halfwords and byte cache can retain plausible coordinates during
    setup, transitions, and overlays. This observer therefore requires a
    lifecycle-recognized player turn, validated map geometry, equal source/cache
    coordinates, and coordinates within the observed map dimensions. It reports
    map position only; it does not identify a selected unit or promise that input
    will be accepted.
    """
    if snapshot.frame != validation.frame:
        raise ValueError("Cursor snapshot and validation must describe the same frame")

    movement_cursor = (
        validation.lifecycle.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
        and validation.lifecycle.engine is LifecycleEngine.BATTLE
        and snapshot.u32(SELECTOR_OBJECT) == UNIT_MOVEMENT_SELECTOR
        and snapshot.u16(CURSOR_GRAPHICS_PROGRESS) == 8
        and snapshot.read(CONTROLLER_LOCK, 1)[0] == 0
        and snapshot.u16(CONTROLLER_STATE) == 13
        and snapshot.u16(0x03003334) == 1
        and any(
            snapshot.u32(SCREEN_PROCESS_POOL + index * SCREEN_PROCESS_STRIDE)
            == UNIT_ACTION_MENU_SCRIPT
            for index in range(SCREEN_PROCESS_COUNT)
        )
        and _observe_selected_unit(snapshot) is not None
    )
    targeting_cursor = _is_fire_targeting(snapshot, validation)
    if (
        validation.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        and not movement_cursor
        and not targeting_cursor
    ):
        return MapCursorObservation(
            snapshot.frame,
            CursorStatus.UNAVAILABLE,
            reasons=(f"Lifecycle phase {validation.lifecycle.phase.value} is not a player turn",),
        )
    if validation.geometry.status is not ValidationStatus.VALID:
        return MapCursorObservation(
            snapshot.frame,
            CursorStatus.UNAVAILABLE,
            reasons=("Map geometry is not validated",),
        )

    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    if movement_cursor or targeting_cursor:
        x, y = snapshot.u16(CURSOR_SOURCE), snapshot.u16(CURSOR_SOURCE + 2)
        if 0 <= x < width and 0 <= y < height:
            return MapCursorObservation(snapshot.frame, CursorStatus.AVAILABLE, x, y)
        return MapCursorObservation(
            snapshot.frame,
            CursorStatus.UNAVAILABLE,
            reasons=("Movement cursor is outside the validated map",),
        )
    source_x, source_y = snapshot.u16(CURSOR_SOURCE), snapshot.u16(CURSOR_SOURCE + 2)
    cache_x, cache_y = snapshot.read(CURSOR_CACHE, 2)
    if (source_x, source_y) != (cache_x, cache_y):
        return MapCursorObservation(
            snapshot.frame,
            CursorStatus.UNAVAILABLE,
            reasons=("Cursor source and cache do not agree",),
        )
    if not (0 <= cache_x < width and 0 <= cache_y < height):
        return MapCursorObservation(
            snapshot.frame,
            CursorStatus.UNAVAILABLE,
            reasons=("Cursor coordinates are outside the validated map",),
        )
    return MapCursorObservation(snapshot.frame, CursorStatus.AVAILABLE, cache_x, cache_y)


def observe_menu(
    snapshot: BattleMemorySnapshot, validation: BattleValidationReport
) -> MenuObservation:
    """Recognize verified command selectors, map input, or a unit-action menu.

    Command choices are exposed only for the ROM-profile-specific selector
    tables whose row mappings, callbacks, and eligibility rules were traced.
    A current-unit pointer is accepted only in the observed unit-action
    process, after checking its army/slot bounds, active-player ownership,
    record coordinates, and logical map-cell reference.
    """
    if snapshot.frame != validation.frame:
        raise ValueError("Menu snapshot and validation must describe the same frame")

    command_menu = _observe_command_menu(snapshot, validation)
    if command_menu is not None:
        return command_menu

    action_menu = _observe_unit_action_choices(snapshot, validation)
    if action_menu is not None:
        return action_menu

    if _is_fire_targeting(snapshot, validation):
        selected = _observe_selected_unit(snapshot)
        if selected is not None:
            return MenuObservation(snapshot.frame, MenuFamily.UNIT_TARGETING, selected)
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_TARGETING,
            reasons=("Acting unit could not be validated during Fire targeting",),
        )

    if validation.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN:
        return MenuObservation(snapshot.frame, MenuFamily.MAP_INPUT)

    if (
        validation.lifecycle.phase is not LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
        or validation.lifecycle.engine is not LifecycleEngine.BATTLE
        or not any(
            snapshot.u32(SCREEN_PROCESS_POOL + index * SCREEN_PROCESS_STRIDE)
            == UNIT_ACTION_MENU_SCRIPT
            for index in range(SCREEN_PROCESS_COUNT)
        )
    ):
        return _unrecognized_menu(
            snapshot,
            validation,
            "No supported menu matches the current lifecycle and process evidence",
        )
    if validation.geometry.status is not ValidationStatus.VALID:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Map geometry is not validated",),
        )

    movement = _observe_unit_movement(snapshot, validation)
    if movement is not None:
        return movement

    pointer = snapshot.u32(CURRENT_UNIT_POINTER)
    relative = pointer - UNIT_BASE
    table_size = 4 * ARMY_STRIDE
    if not 0 <= relative < table_size:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Current-unit pointer is outside the bounded unit table",),
        )
    army_index, army_offset = divmod(relative, ARMY_STRIDE)
    unit_slot, record_remainder = divmod(army_offset, UNIT_STRIDE)
    if record_remainder or not 1 <= unit_slot <= UNITS_PER_ARMY:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Current-unit pointer is not an active slot boundary",),
        )

    record = snapshot.read(pointer, UNIT_STRIDE)
    if record[0] not in UNIT_TYPES:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Current-unit record is not an active supported unit",),
        )
    army_slot = army_index + 1
    if snapshot.u16(ACTIVE_PLAYER) != army_slot:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Current-unit army does not match the active player slot",),
        )

    x, y = record[2], record[3]
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    cursor_x, cursor_y = snapshot.read(CURSOR_CACHE, 2)
    if (x, y) != (cursor_x, cursor_y):
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Selected unit coordinates do not match the map cursor",),
        )
    if not (x < width and y < height):
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Selected unit coordinates are outside the validated map",),
        )

    row_offset = snapshot.u16(MAP_BASE + 0x417A + 2 * y)
    logical_unit = snapshot.read(MAP_BASE + 0x051A + row_offset + x, 1)[0]
    unit_index = relative // UNIT_STRIDE
    if logical_unit != unit_index:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Logical map occupant does not match the selected unit record",),
        )

    selected = SelectedUnitObservation(pointer, army_slot, unit_slot, record[0], x, y)
    return MenuObservation(snapshot.frame, MenuFamily.UNIT_ACTION, selected)


def _observe_unit_movement(
    snapshot: BattleMemorySnapshot, validation: BattleValidationReport
) -> MenuObservation | None:
    if (
        snapshot.u32(SELECTOR_OBJECT) != UNIT_MOVEMENT_SELECTOR
        or snapshot.u16(CURSOR_GRAPHICS_PROGRESS) != 8
        or snapshot.read(CONTROLLER_LOCK, 1)[0] != 0
        or snapshot.u16(CONTROLLER_STATE) != 13
        or snapshot.u16(0x03003334) != 1
    ):
        return None
    selected = _observe_selected_unit(snapshot)
    if selected is None:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_MOVEMENT,
            reasons=("Selected unit could not be validated for movement",),
        )
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    x, y = snapshot.u16(CURSOR_SOURCE), snapshot.u16(CURSOR_SOURCE + 2)
    if not (x < width and y < height):
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_MOVEMENT,
            reasons=("Movement cursor is outside the validated map",),
        )
    return MenuObservation(snapshot.frame, MenuFamily.UNIT_MOVEMENT, selected)


def _observe_unit_action_choices(
    snapshot: BattleMemorySnapshot, validation: BattleValidationReport
) -> MenuObservation | None:
    if (
        validation.lifecycle.phase is not LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
        or validation.lifecycle.engine is not LifecycleEngine.BATTLE
        or not any(
            snapshot.u32(SCREEN_PROCESS_POOL + index * SCREEN_PROCESS_STRIDE)
            == UNIT_ACTION_MENU_SCRIPT
            for index in range(SCREEN_PROCESS_COUNT)
        )
        or snapshot.u32(SELECTOR_OBJECT) != UNIT_ACTION_SELECTOR
        or snapshot.u32(SELECTOR_TABLE) != UNIT_ACTION_TABLE
        or snapshot.u16(CONTROLLER_STATE) != 13
        or snapshot.read(CONTROLLER_LOCK, 1)[0] != 1
        or snapshot.u16(0x03003334) != 4
    ):
        return None
    selected = _observe_selected_unit(snapshot)
    count = snapshot.read(SELECTOR_ROW_COUNT, 1)[0]
    row = snapshot.read(SELECTOR_SELECTED_ROW, 1)[0]
    ids = tuple(snapshot.read(SELECTOR_ITEM_IDS, count)) if count == 2 else ()
    if (
        selected is None
        or len(ids) != 2
        or ids.count(0x0A) != 1
        or any(item_id not in (0, 2, 4, 0x0A, 0x0B) for item_id in ids)
        or row >= 2
    ):
        return None
    if not _menu_rules_allow_dispatch(snapshot):
        return None
    capture_eligible = _selected_unit_can_capture(snapshot, selected)
    items = tuple(
        MenuItem.WAIT
        if item_id == 0x0A
        else MenuItem.FIRE
        if item_id == 0
        else MenuItem.CAPTURE
        if item_id == 2 and capture_eligible
        else MenuItem.OTHER_UNIT_ACTION
        for item_id in ids
    )
    return MenuObservation(
        snapshot.frame,
        MenuFamily.UNIT_ACTION_CHOICES,
        selected_unit=selected,
        selected_item=items[row],
        actionable=True,
        items=items,
    )


def _selected_unit_can_capture(
    snapshot: BattleMemorySnapshot, selected: SelectedUnitObservation
) -> bool:
    """Constrain the verified Capture row ID to an eligible unit on a property."""
    if selected.unit_type not in (1, 2):  # Infantry and Mech
        return False
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    if not (0 <= selected.x < width and 0 <= selected.y < height):
        return False
    terrain_owner = snapshot.read(MAP_BASE + 0x1432 + selected.y * width + selected.x, 1)[0]
    terrain_class, owner_code = terrain_owner & 31, terrain_owner >> 5
    return terrain_class in (6, 8, 14) and owner_code != selected.army_slot


def _is_fire_targeting(snapshot: BattleMemorySnapshot, validation: BattleValidationReport) -> bool:
    return (
        validation.lifecycle.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
        and validation.lifecycle.engine is LifecycleEngine.BATTLE
        and FIRE_TARGETING_SCRIPT in validation.lifecycle.active_process_scripts
        and snapshot.u32(SELECTOR_OBJECT) == UNIT_MOVEMENT_SELECTOR
        and snapshot.u16(CURSOR_GRAPHICS_PROGRESS) == 8
        and snapshot.u16(CONTROLLER_STATE) == 13
        and snapshot.read(CONTROLLER_LOCK, 1)[0] == 1
        and snapshot.u16(0x03003334) == 4
    )


def _observe_selected_unit(snapshot: BattleMemorySnapshot) -> SelectedUnitObservation | None:
    pointer = snapshot.u32(CURRENT_UNIT_POINTER)
    relative = pointer - UNIT_BASE
    if not 0 <= relative < 4 * ARMY_STRIDE:
        return None
    army_index, army_offset = divmod(relative, ARMY_STRIDE)
    unit_slot, remainder = divmod(army_offset, UNIT_STRIDE)
    if remainder or not 1 <= unit_slot <= UNITS_PER_ARMY:
        return None
    record = snapshot.read(pointer, UNIT_STRIDE)
    if record[0] not in UNIT_TYPES:
        return None
    army_slot = army_index + 1
    if snapshot.u16(ACTIVE_PLAYER) != army_slot:
        return None
    x, y = record[2], record[3]
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    if not (x < width and y < height):
        return None
    row_offset = snapshot.u16(MAP_BASE + 0x417A + 2 * y)
    logical_unit = snapshot.read(MAP_BASE + 0x051A + row_offset + x, 1)[0]
    if logical_unit != relative // UNIT_STRIDE:
        return None
    return SelectedUnitObservation(pointer, army_slot, unit_slot, record[0], x, y)


def _observe_command_menu(
    snapshot: BattleMemorySnapshot, validation: BattleValidationReport
) -> MenuObservation | None:
    """Resolve only known, active selector objects in the battle menu state."""
    if (
        validation.lifecycle.phase is not LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
        or validation.lifecycle.engine is not LifecycleEngine.BATTLE
        or snapshot.u16(CONTROLLER_STATE) != 13
        or snapshot.read(CONTROLLER_LOCK, 1)[0] != 1
        or snapshot.u32(SELECTOR_OBJECT) != 0x0848A42C
    ):
        return None

    table = snapshot.u32(SELECTOR_TABLE)
    table_spec = _MENU_TABLES.get(table)
    if table_spec is None:
        return None
    family_name, expected_count, expected_items = table_spec
    count = snapshot.read(SELECTOR_ROW_COUNT, 1)[0]
    selected_row = snapshot.read(SELECTOR_SELECTED_ROW, 1)[0]
    item_ids = tuple(snapshot.read(SELECTOR_ITEM_IDS, count)) if count <= 5 else ()
    if count != expected_count or item_ids != expected_items or selected_row >= count:
        return _unrecognized_menu(
            snapshot,
            validation,
            "Active selector does not match a verified menu table",
        )

    if not _menu_rules_allow_dispatch(snapshot):
        return _unrecognized_menu(
            snapshot,
            validation,
            "Map menu eligibility rules require unsupported evaluation",
        )

    return MenuObservation(
        snapshot.frame,
        MenuFamily(family_name),
        selected_item=_MENU_ITEMS[family_name][selected_row],
        actionable=True,
    )


def _menu_rules_allow_dispatch(snapshot: BattleMemorySnapshot) -> bool:
    """Null map-header rule lists allow dispatch; other lists stay unsupported."""
    map_id = snapshot.read(MAP_ID, 1)[0]
    return snapshot.layout.menu_rules_by_map[map_id] == 0


def _unrecognized_menu(
    snapshot: BattleMemorySnapshot,
    validation: BattleValidationReport,
    reason: str,
) -> MenuObservation:
    """Return unresolved status together with the evidence needed to revisit it."""
    controller = BattleControlObservation(
        mode=snapshot.u32(0x03003F3C),
        state=snapshot.u16(CONTROLLER_STATE),
        lock_count=snapshot.read(CONTROLLER_LOCK, 1)[0],
        input_gate=int.from_bytes(snapshot.read(0x030040E4, 2), "little", signed=True),
        input_state=snapshot.u16(0x03003334),
    )
    state = UnrecognizedUIState(
        frame=snapshot.frame,
        lifecycle=validation.lifecycle,
        controller=controller,
        selector_object=snapshot.u32(SELECTOR_OBJECT),
        selector_table=snapshot.u32(SELECTOR_TABLE),
        reason=reason,
    )
    return MenuObservation(
        snapshot.frame,
        MenuFamily.UNRESOLVED,
        reasons=(reason,),
        unrecognized=state,
    )
