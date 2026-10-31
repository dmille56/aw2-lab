"""Versioned structured observation envelope for verified Milestone 2 state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from aw2_lab.lifecycle import LifecycleAssessment
from aw2_lab.rom_profile import AW2_US_REVISION_0, RomProfile, UnsupportedRomError
from aw2_lab.state_validation import BattleValidationReport
from aw2_lab.ui_state import MapCursorObservation, MenuObservation

GAME_STATE_SCHEMA_VERSION = 4


class ValueStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ObservedValue[T]:
    """A value with explicit availability; zero and an empty roster are valid values."""

    status: ValueStatus
    value: T | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is ValueStatus.AVAILABLE:
            if self.value is None:
                raise ValueError("An available observation requires a value")
        elif self.value is not None or not self.reasons:
            raise ValueError("An absent observation requires reasons and no value")


class Weather(StrEnum):
    CLEAR = "clear"
    SNOW = "snow"
    RAIN = "rain"


@dataclass(frozen=True, slots=True)
class TileState:
    x: int
    y: int
    graphical_tile_id: int
    terrain_class: int
    owner_slot: int


@dataclass(frozen=True, slots=True)
class MapState:
    width: int
    height: int
    tiles: tuple[TileState, ...]


@dataclass(frozen=True, slots=True)
class PropertyState:
    """A property or silo feature; capture progress belongs to its capturing unit."""

    x: int
    y: int
    terrain_class: int
    owner_slot: int


@dataclass(frozen=True, slots=True)
class PlayerState:
    slot: int
    control_type: int
    team_id: int
    co_id: int
    funds: int
    active_power: int
    power_meter: ObservedValue[int]
    power_use_counter: ObservedValue[int]


@dataclass(frozen=True, slots=True)
class UnitState:
    """Verified record fields; reference is a reusable slot, not a lifetime ID.

    Embarked units retain record coordinates which may differ from their transport.
    Unassigned status/fuel bits and HUD health rounding are intentionally omitted.
    """

    reference: int
    army_slot: int
    unit_slot: int
    unit_type: int
    x: int
    y: int
    internal_health: int
    ammo: int
    fuel: int
    used_this_turn: bool
    embarked: bool
    capture_points: int
    cargo_references: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BattleState:
    day: int
    active_player_slot: int
    weather: ObservedValue[Weather]
    map: MapState
    properties: tuple[PropertyState, ...]
    players: tuple[PlayerState, ...]
    units: tuple[UnitState, ...]
    co_effects_enabled: ObservedValue[bool] = ObservedValue(
        ValueStatus.UNKNOWN, None, ("CO effects option was not observed",)
    )
    fog_enabled: ObservedValue[bool] = ObservedValue(
        ValueStatus.UNKNOWN, None, ("Fog option was not observed",)
    )


@dataclass(frozen=True, slots=True)
class StateContext:
    """ROM and decoder identity required to interpret this state document."""

    rom_profile: RomProfile

    def __post_init__(self) -> None:
        if self.rom_profile != AW2_US_REVISION_0:
            raise UnsupportedRomError("GameState requires the supported US ROM profile")


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
    """One coherent observation, with battle values gated by lifecycle and validation."""

    schema_version: int
    frame: int
    context: StateContext
    validation: BattleValidationReport
    ui: UIStateObservation
    battle: ObservedValue[BattleState]

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
        if self.battle.status is ValueStatus.AVAILABLE and not self.validation.can_decode_live:
            raise ValueError("Available battle data requires passing live validation")

    @property
    def lifecycle(self) -> LifecycleAssessment:
        """Lifecycle classification from the same validated frame."""
        return self.validation.lifecycle

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible document whose version gates interpretation."""
        return asdict(self)
