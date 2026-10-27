"""Versioned structured observation envelope for verified Milestone 2 state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from aw2_lab.lifecycle import LifecycleAssessment
from aw2_lab.rom_profile import AW2_US_REVISION_0, RomProfile, UnsupportedRomError
from aw2_lab.state_validation import BattleValidationReport
from aw2_lab.ui_state import MapCursorObservation, MenuObservation

GAME_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StateContext:
    """ROM and decoder identity required to interpret this state document."""

    rom_profile: RomProfile

    def __post_init__(self) -> None:
        if self.rom_profile != AW2_US_REVISION_0:
            raise UnsupportedRomError("GameState schema v1 requires the supported US ROM profile")


@dataclass(frozen=True, slots=True)
class UIStateObservation:
    """Cursor and menu observations made from the same emulator frame."""

    frame: int
    map_cursor: MapCursorObservation
    menu: MenuObservation

    def __post_init__(self) -> None:
        if self.map_cursor.frame != self.frame or self.menu.frame != self.frame:
            raise ValueError("UI observations must describe the GameState frame")


@dataclass(frozen=True, slots=True)
class GameState:
    """Versioned envelope of verified lifecycle, validation, and UI observations.

    Schema v1 intentionally reports structural validation and UI observations;
    it does not claim to decode full map, property, player, or unit records.
    """

    schema_version: int
    frame: int
    context: StateContext
    validation: BattleValidationReport
    ui: UIStateObservation

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError("GameState schema version must be an integer")
        if self.schema_version != GAME_STATE_SCHEMA_VERSION:
            raise ValueError(f"Unsupported GameState schema version: {self.schema_version!r}")
        if isinstance(self.frame, bool) or not isinstance(self.frame, int):
            raise TypeError("GameState frame must be an integer")
        if not 0 <= self.frame < 1 << 32:
            raise ValueError("GameState frame must fit the bridge's unsigned 32-bit frame")
        if self.validation.frame != self.frame or self.ui.frame != self.frame:
            raise ValueError("GameState components must describe the same emulator frame")

    @property
    def lifecycle(self) -> LifecycleAssessment:
        """Lifecycle classification from the same validated frame."""
        return self.validation.lifecycle

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible document whose version gates interpretation."""
        return asdict(self)
