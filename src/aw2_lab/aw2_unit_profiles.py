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
from aw2_lab.state_model import BattleState, ValueStatus, Weather

CAPTURABLE_TERRAINS = frozenset({6, 8, 14})  # city, HQ, and base on the supported ROM
CAPTURE_UNIT_TYPES = frozenset({1, 2})  # Infantry and Mech


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

    Movement consumes fuel in both fog modes. Occupants, fog blockers,
    remaining movement and turn-start fuel upkeep are separate rules.
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


def collapse_route(
    path: Sequence[tuple[int, int]], *, start: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    """Return the tiles AW2 actually charges for a walked route.

    Verified against the supported US ROM: a step that re-enters a tile already
    in the route retracts the movement arrow back to that tile instead of
    extending it, so only the remaining simple path is paid for. The reached
    tile is unchanged, so the endpoint stays ``path[-1]``.
    """
    route: list[tuple[int, int]] = [start]
    for point in path:
        if point in route:
            while route and route[-1] != point:
                route.pop()
        else:
            route.append(point)
    return tuple(route[1:])


def observed_rule_context(battle: BattleState, player_slot: int) -> RuleContext | None:
    """Return the acting player's CO/power rules, or None when they are unobserved."""
    enabled = battle.co_effects_enabled
    if enabled.status is not ValueStatus.AVAILABLE or enabled.value is None:
        return None
    player = next((item for item in battle.players if item.slot == player_slot), None)
    if player is None:
        return None
    if enabled.value is False:
        return RuleContext()
    return RuleContext(player.co_id, player.active_power)


def possible_rule_contexts(context: RuleContext | None) -> tuple[RuleContext, ...]:
    """Return the observed context, or every supported context when it is unknown."""
    if context is not None:
        return (context,)
    return (
        BASELINE_RULES,
        *(RuleContext(co, power) for co in range(19) for power in range(3)),
    )


def _route_budgets(
    *,
    unit_type: int,
    visited_classes: tuple[int, ...] | None,
    charged_classes: tuple[int, ...],
    charged_steps: int,
    context: RuleContext | None,
    weather: Weather | None,
) -> list[tuple[int, int]]:
    """List (cost, movement allowance) for each passable CO/power/weather pairing.

    Complete routes are evaluated under one context at a time. Mixing the
    cheapest tile from different CO/weather tables could accept an impossible
    budget. ``visited_classes`` is every tile the movement arrow tries to enter,
    which a context must tolerate; ``charged_classes`` is the collapsed route
    that actually spends movement allowance.
    """
    budgets: list[tuple[int, int]] = []
    for candidate in possible_rule_contexts(context):
        allowance, _ = candidate.unit_limits(unit_type)
        for condition in (weather,) if weather is not None else tuple(Weather):
            if visited_classes is None:
                cost: int | None = charged_steps
            elif route_cost(unit_type, visited_classes, condition, context=candidate) is None:
                continue
            else:
                cost = route_cost(unit_type, charged_classes, condition, context=candidate)
            if cost is not None:
                budgets.append((cost, allowance))
    return budgets


def preflight_move(
    *,
    unit_type: int,
    path: tuple[tuple[int, int], ...],
    start: tuple[int, int] | None = None,
    terrain_classes: tuple[int, ...] | None = None,
    context: RuleContext | None = None,
    weather: Weather | None = None,
    fuel: int | None = None,
) -> None:
    """Reject routes that cannot fit inside movement allowance or fuel.

    Terrain costs come from the observed weather and CO rules. AW2 remains
    authoritative for occupancy, fog-hidden blockers, and the tile the unit
    actually reaches; this check only rejects routes known to be impossible.
    With ``start`` given, a route that doubles back is collapsed first because
    AW2 retracts the movement arrow over tiles it has already visited.
    """
    if unit_type not in UNIT_PROFILES:
        return
    if terrain_classes is not None and len(terrain_classes) != len(path):
        raise ValueError("Each path tile requires a terrain class")
    if not path:
        return
    if start is None:
        charged_path, charged_classes = path, terrain_classes or ()
    else:
        charged_path = collapse_route(path, start=start)
        if terrain_classes is None:
            charged_classes = ()
        else:
            terrain_by_tile = dict(zip(path, terrain_classes))
            charged_classes = tuple(terrain_by_tile[point] for point in charged_path)
    budgets = _route_budgets(
        unit_type=unit_type,
        visited_classes=terrain_classes,
        charged_classes=charged_classes,
        charged_steps=len(charged_path),
        context=context,
        weather=weather,
    )
    if not budgets:
        raise ValueError("Requested route enters impassable terrain for the unit")
    feasible = [(cost, allowance) for cost, allowance in budgets if cost <= allowance]
    if not feasible:
        raise ValueError("Requested route exceeds the unit's maximum movement allowance")
    if fuel is not None and not any(cost <= fuel for cost, _ in feasible):
        raise ValueError("Requested route exceeds the unit's remaining fuel")


def preflight_move_attack(
    *,
    unit_type: int,
    ammo: int,
    path: tuple[tuple[int, int], ...],
    start: tuple[int, int],
    target: tuple[int, int],
    target_unit_type: int | None = None,
    terrain_classes: tuple[int, ...] | None = None,
    context: RuleContext | None = None,
    weather: Weather | None = None,
    fuel: int | None = None,
) -> None:
    """Reject impossible actions across all supported CO/power configurations.

    Observed context and weather select exact movement costs and limits.
    Missing inputs retain permissive bounds; AW2 checks occupants and fog.
    Fuel is consumed with and without fog; an absent fuel value skips that bound.
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

    preflight_move(
        unit_type=unit_type,
        path=path,
        start=start,
        terrain_classes=terrain_classes,
        context=context,
        weather=weather,
        fuel=fuel,
    )
    maximum_range = max(
        candidate.unit_limits(unit_type)[1] for candidate in possible_rule_contexts(context)
    )

    if not any(
        profile.minimum_range <= abs(x - target[0]) + abs(y - target[1]) <= maximum_range
        for x, y in (start, *collapse_route(path, start=start))
    ):
        raise ValueError("Target is outside the unit's possible attack range along the route")
