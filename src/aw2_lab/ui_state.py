"""Typed observations for the map cursor in the verified Versus battle context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.state_validation import (
    MAP_BASE,
    BattleMemorySnapshot,
    BattleValidationReport,
    ValidationStatus,
)

CURSOR_SOURCE = 0x030033E4
CURSOR_CACHE = 0x03003140


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
