"""AW2 US unit/terrain facts and bounded preflight; see AW2-UNIT-TERRAIN-RULES.md."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from aw2_lab.aw2_rules_data import (
    CO_FUEL_DISCOUNTS,
    CO_MOVEMENT_VARIANTS,
    CO_UNIT_MODIFIERS,
    TERRAIN_COSTS,
    TERRAIN_NAMES,
    UNIT_DATA,
    UNIT_FUEL_UPKEEP,
    UNIT_ZERO_FUEL_LOSS,
)
from aw2_lab.state_model import Weather


class MovementType(IntEnum):
    FOOT = 0
    MECH = 1
    TREADS = 2
    WHEELS = 3
    AIR = 4
    SHIP = 5
    LANDER = 6


class WeaponType(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"

    @property
    def ammo_cost(self) -> int:
        return 1 if self is WeaponType.PRIMARY else 0


@dataclass(frozen=True, slots=True)
class UnitProfile:
    name: str
    movement_type: MovementType
    movement: int
    ammo_capacity: int
    vision: int
    minimum_range: int
    maximum_range: int
    fuel_capacity: int
    cost: int
    daily_fuel: int
    destroyed_at_zero_fuel: bool
    primary_targets: frozenset[int]
    secondary_targets: frozenset[int]

    @property
    def can_attack(self) -> bool:
        return bool(self.primary_targets or self.secondary_targets)

    @property
    def indirect(self) -> bool:
        return self.minimum_range > 1

    def available_weapons(self, target_type: int, ammo: int) -> tuple[WeaponType, ...]:
        """List compatible weapons; secondary weapons do not spend main ammo.

        Target type 25 denotes the ROM's submerged-submarine combat column,
        not a supported logical unit-record type. Visibility is decided by AW2.
        """
        return tuple(
            weapon
            for weapon, available in (
                (WeaponType.PRIMARY, ammo > 0 and target_type in self.primary_targets),
                (WeaponType.SECONDARY, target_type in self.secondary_targets),
            )
            if available
        )


UNIT_PROFILES = {
    unit_type: UnitProfile(
        name=row[0],
        movement_type=MovementType(row[1]),
        movement=row[2],
        ammo_capacity=row[3],
        vision=row[4],
        minimum_range=row[5],
        maximum_range=row[6],
        fuel_capacity=row[7],
        cost=row[8],
        daily_fuel=UNIT_FUEL_UPKEEP[unit_type],
        destroyed_at_zero_fuel=unit_type in UNIT_ZERO_FUEL_LOSS,
        primary_targets=frozenset(row[9]),
        secondary_targets=frozenset(row[10]),
    )
    for unit_type, row in UNIT_DATA.items()
}


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Explicit CO settings; None selects baseline units with CO effects off."""

    co_id: int | None = None
    active_power: int = 0

    def __post_init__(self) -> None:
        if self.co_id is not None and not 0 <= self.co_id <= 18:
            raise ValueError("CO ID must be in 0..18")
        if self.active_power not in (0, 1, 2):
            raise ValueError("active_power must be 0, 1, or 2")
        if self.co_id is None and self.active_power:
            raise ValueError("An active power requires a CO ID")

    def unit_limits(self, unit_type: int) -> tuple[int, int]:
        """Return movement allowance and maximum attack range with CO effects."""
        profile = UNIT_PROFILES[unit_type]
        move_bonus, range_bonus = CO_UNIT_MODIFIERS.get((self.co_id, self.active_power), {}).get(
            unit_type, (0, 0)
        )
        return profile.movement + move_bonus, profile.maximum_range + range_bonus


BASELINE_RULES = RuleContext()


def turn_start_fuel(
    unit_type: int,
    *,
    context: RuleContext = BASELINE_RULES,
    embarked: bool = False,
    on_owned_service_property: bool = False,
    submerged: bool = False,
) -> int:
    """Normal-rule upkeep before replenishment, from ROM routine 0x080253B0.

    A service property must match the unit (e.g. owned airport for aircraft).
    Visibility, depletion removal and replenishment ordering remain in AW2.
    """
    unit = UNIT_PROFILES[unit_type]
    if submerged and unit_type != 24:
        raise ValueError("Only a Submarine can be submerged")
    if embarked or on_owned_service_property:
        return 0
    cost = 5 if submerged else unit.daily_fuel
    if unit.movement_type is MovementType.AIR:
        cost -= CO_FUEL_DISCOUNTS.get((context.co_id, context.active_power), 0)
    return max(0, cost)


def movement_cost(
    terrain_class: int,
    movement_type: MovementType,
    weather: Weather = Weather.CLEAR,
    *,
    context: RuleContext = BASELINE_RULES,
) -> int | None:
    """Return per-tile movement/fuel cost, or None for impassable terrain.

    Fuel debit applies when normal fuel consumption is enabled. Occupants,
    fog, remaining movement and turn-start fuel upkeep are separate rules.
    """
    if terrain_class not in TERRAIN_NAMES:
        raise ValueError(f"Unknown terrain class: {terrain_class}")
    variants = CO_MOVEMENT_VARIANTS.get(
        (context.co_id, context.active_power), ("clear", "snow", "rain")
    )
    variant = variants[(Weather.CLEAR, Weather.SNOW, Weather.RAIN).index(weather)]
    return TERRAIN_COSTS[variant][terrain_class][movement_type]


def route_cost(
    unit_type: int,
    terrain_classes: Sequence[int],
    weather: Weather = Weather.CLEAR,
    *,
    context: RuleContext = BASELINE_RULES,
) -> int | None:
    """Sum entered tiles (exclude the starting tile); None means impassable."""
    movement_type = UNIT_PROFILES[unit_type].movement_type
    total = 0
    for terrain in terrain_classes:
        cost = movement_cost(terrain, movement_type, weather, context=context)
        if cost is None:
            return None
        total += cost
    return total


def _maximum_bonus(unit_type: int, field: int) -> int:
    return max(0, *(row.get(unit_type, (0, 0))[field] for row in CO_UNIT_MODIFIERS.values()))


def preflight_move_attack(
    *,
    unit_type: int,
    ammo: int,
    path: tuple[tuple[int, int], ...],
    start: tuple[int, int],
    target: tuple[int, int],
    target_unit_type: int | None = None,
    terrain_classes: tuple[int, ...] | None = None,
) -> None:
    """Reject impossible actions across all supported CO/power configurations.

    The observation does not expose whether CO effects or fuel consumption
    are enabled. Exact budgets use explicit RuleContext/route_cost calls;
    executor checks use the most permissive costs and limits across contexts.
    """
    profile = UNIT_PROFILES.get(unit_type)
    if profile is None:
        return
    if not profile.can_attack:
        raise ValueError("Unit type has no weapons")
    if not profile.secondary_targets and ammo <= 0:
        raise ValueError("Unit has no ammunition for its only weapons")
    if target_unit_type is not None and not profile.available_weapons(target_unit_type, ammo):
        raise ValueError("No compatible weapon with ammunition is available for the target")
    if path and profile.indirect:
        raise ValueError("Indirect units cannot move and attack in the same turn")

    minimum_cost = len(path)
    if terrain_classes is not None:
        if len(terrain_classes) != len(path):
            raise ValueError("Each path tile requires a terrain class")
        minimum_cost = 0
        for terrain in terrain_classes:
            if terrain not in TERRAIN_NAMES:
                raise ValueError(f"Unknown terrain class: {terrain}")
            possible_costs = tuple(
                table[terrain][profile.movement_type] for table in TERRAIN_COSTS.values()
            )
            costs = tuple(cost for cost in possible_costs if cost is not None)
            if not costs:
                raise ValueError("Requested route enters impassable terrain for the unit")
            minimum_cost += min(costs)
    if minimum_cost > profile.movement + _maximum_bonus(unit_type, 0):
        raise ValueError("Requested route exceeds the unit's maximum movement allowance")

    maximum_range = profile.maximum_range + _maximum_bonus(unit_type, 1)
    if not any(
        profile.minimum_range <= abs(x - target[0]) + abs(y - target[1]) <= maximum_range
        for x, y in (start, *path)
    ):
        raise ValueError("Target is outside the unit's possible attack range along the route")
