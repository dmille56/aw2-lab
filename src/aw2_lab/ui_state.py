"""Typed observations for the map cursor in the verified Versus battle context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aw2_lab.lifecycle import LifecycleEngine, LifecyclePhase
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
    UNIT_ACTION = "unit_action"
    UNRESOLVED = "unresolved"


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
    """Recognized menu family and any unit selected for its action menu."""

    frame: int
    family: MenuFamily
    selected_unit: SelectedUnitObservation | None = None
    reasons: tuple[str, ...] = ()


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

    if validation.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
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
    """Recognize map input or a verified unit-action menu and resolve its unit.

    The general command menu and its highlighted item remain unresolved. A
    current-unit pointer is accepted only in the observed unit-action process,
    after checking its army/slot bounds, active-player ownership, record
    coordinates, and logical map-cell reference.
    """
    if snapshot.frame != validation.frame:
        raise ValueError("Menu snapshot and validation must describe the same frame")

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
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNRESOLVED,
            reasons=("No supported menu process identifies the current menu",),
        )
    if validation.geometry.status is not ValidationStatus.VALID:
        return MenuObservation(
            snapshot.frame,
            MenuFamily.UNIT_ACTION,
            reasons=("Map geometry is not validated",),
        )

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
