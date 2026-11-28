"""Player-specific planning data from one committed match observation."""

from heapq import heappop, heappush
from typing import Literal

from pydantic import BaseModel

from aw2_lab.api_contract import StateResponse
from aw2_lab.aw2_rules_data import TERRAIN_NAMES
from aw2_lab.aw2_unit_profiles import UNIT_PROFILES, movement_cost, observed_rule_context
from aw2_lab.capture_rules import CAPTURABLE_TERRAINS, CAPTURE_UNIT_TYPES
from aw2_lab.match_contract import ContractModel, Coordinate, MatchLifecycle, PlayerSlot, Revision
from aw2_lab.match_observation import ActionReadiness, IdentityStatus, has_unsettled_map_cursor
from aw2_lab.production_rules import PRODUCTION_BY_TERRAIN
from aw2_lab.state_model import BattleState, UnitState, ValueStatus


class BriefUnit(ContractModel):
    unit_id: str
    unit_type: str
    tile: Coordinate
    hp: int


class AffordableUnit(ContractModel):
    unit_type: str
    cost: int


class EmptyFacility(ContractModel):
    tile: Coordinate
    facility: str
    affordable_units: tuple[AffordableUnit, ...]


class ReachableTile(ContractModel):
    tile: Coordinate
    path: tuple[Coordinate, ...]
    can_capture: bool


class TurnBrief(ContractModel):
    player_slot: PlayerSlot
    revision: Revision
    lifecycle: MatchLifecycle
    turn_ready: bool = False
    cursor_recovery_available: bool = False
    day: int | None = None
    funds: int | None = None
    ready_units: tuple[BriefUnit, ...] = ()
    opposing_targets: tuple[BriefUnit, ...] = ()
    empty_facilities: tuple[EmptyFacility, ...] = ()
    movement_unit_id: str | None = None
    reachable_tiles: tuple[ReachableTile, ...] | None = None


BriefFormat = Literal["standard", "compact"]
TilePair = tuple[int, int]
UnitRow = tuple[str, str, TilePair, int]
PurchaseRow = tuple[str, int]
MovementRow = tuple[TilePair, tuple[TilePair, ...], bool]


class FacilityGroup(BaseModel):
    facility: str
    tiles: tuple[TilePair, ...]
    affordable_units: tuple[PurchaseRow, ...]


class CompactTurnBrief(ContractModel):
    format: Literal["compact"] = "compact"
    player_slot: PlayerSlot
    revision: Revision
    lifecycle: MatchLifecycle
    turn_ready: bool
    cursor_recovery_available: bool
    day: int | None = None
    funds: int | None = None
    ready_units: tuple[UnitRow, ...]
    opposing_targets: tuple[UnitRow, ...]
    empty_facilities: tuple[FacilityGroup, ...]
    movement_unit_id: str | None = None
    reachable_tiles: tuple[MovementRow, ...] | None = None


def compact_turn_brief(brief: TurnBrief) -> CompactTurnBrief:
    def tile_pair(tile: Coordinate) -> TilePair:
        return tile.x, tile.y

    def unit_row(unit: BriefUnit) -> UnitRow:
        return unit.unit_id, unit.unit_type, tile_pair(unit.tile), unit.hp

    facilities: dict[tuple[str, tuple[PurchaseRow, ...]], list[TilePair]] = {}
    for facility in brief.empty_facilities:
        menu = tuple((unit.unit_type, unit.cost) for unit in facility.affordable_units)
        facilities.setdefault((facility.facility, menu), []).append(tile_pair(facility.tile))

    return CompactTurnBrief(
        player_slot=brief.player_slot,
        revision=brief.revision,
        lifecycle=brief.lifecycle,
        turn_ready=brief.turn_ready,
        cursor_recovery_available=brief.cursor_recovery_available,
        day=brief.day,
        funds=brief.funds,
        ready_units=tuple(map(unit_row, brief.ready_units)),
        opposing_targets=tuple(map(unit_row, brief.opposing_targets)),
        empty_facilities=tuple(
            FacilityGroup(facility=facility, tiles=tuple(tiles), affordable_units=menu)
            for (facility, menu), tiles in facilities.items()
        ),
        movement_unit_id=brief.movement_unit_id,
        reachable_tiles=(
            None
            if brief.reachable_tiles is None
            else tuple(
                (tile_pair(move.tile), tuple(map(tile_pair, move.path)), move.can_capture)
                for move in brief.reachable_tiles
            )
        ),
    )


def build_turn_brief(
    state: StateResponse, slot: PlayerSlot, *, unit_id: str | None = None
) -> TurnBrief:
    """Return actionable choices only for the slot's settled, active turn."""
    brief = TurnBrief(
        player_slot=slot,
        revision=state.summary.revision,
        lifecycle=state.summary.lifecycle,
        movement_unit_id=unit_id,
    )
    observation = state.observation
    if (
        not state.settled
        or state.summary.lifecycle is not MatchLifecycle.PLAYABLE
        or observation is None
        or observation.identity_status is not IdentityStatus.AVAILABLE
    ):
        return brief
    observed_battle = observation.game_state.battle
    battle = observed_battle.value
    slot_number = list(PlayerSlot).index(slot) + 1
    if (
        observed_battle.status is not ValueStatus.AVAILABLE
        or battle is None
        or battle.active_player_slot != slot_number
    ):
        return brief
    if has_unsettled_map_cursor(observation.game_state):
        return brief.model_copy(update={"cursor_recovery_available": True, "day": battle.day})
    if observation.action_readiness is not ActionReadiness.READY:
        return brief
    player = next((item for item in battle.players if item.slot == slot_number), None)
    if player is None:
        return brief
    identities = {item.reference: item.identity_id for item in observation.unit_identities}
    units = tuple(unit for unit in battle.units if not unit.embarked)
    occupied = {(unit.x, unit.y): unit for unit in units}
    allied_slots = {item.slot for item in battle.players if item.team_id == player.team_id}
    ready = tuple(
        unit
        for unit in units
        if unit.army_slot == slot_number
        and not unit.used_this_turn
        and unit.reference in identities
    )

    def describe(unit: UnitState) -> BriefUnit:
        profile = UNIT_PROFILES.get(unit.unit_type)
        return BriefUnit(
            unit_id=identities[unit.reference],
            unit_type=profile.name if profile else f"Unit {unit.unit_type}",
            tile=Coordinate(x=unit.x, y=unit.y),
            hp=(unit.internal_health + 9) // 10,
        )

    facilities = []
    for prop in battle.properties:
        facility = PRODUCTION_BY_TERRAIN.get(prop.terrain_class)
        if prop.owner_slot != slot_number or (prop.x, prop.y) in occupied or facility is None:
            continue
        facilities.append(
            EmptyFacility(
                tile=Coordinate(x=prop.x, y=prop.y),
                facility=facility.name,
                affordable_units=tuple(
                    AffordableUnit(unit_type=profile.name, cost=profile.cost)
                    for kind in facility.unit_types
                    if (profile := UNIT_PROFILES[kind]).cost <= player.funds
                ),
            )
        )

    selected = next((unit for unit in ready if identities[unit.reference] == unit_id), None)
    # Fog-disabled battles expose enemy positions and occupancy to the player.
    clear_visibility = (
        battle.fog_enabled.status is ValueStatus.AVAILABLE and battle.fog_enabled.value is False
    )
    return brief.model_copy(
        update={
            "turn_ready": True,
            "day": battle.day,
            "funds": player.funds,
            "ready_units": tuple(map(describe, ready)),
            "opposing_targets": tuple(
                describe(unit)
                for unit in units
                if clear_visibility
                and unit.army_slot not in allied_slots
                and unit.reference in identities
                and not unit.submerged
            ),
            "empty_facilities": tuple(facilities),
            "reachable_tiles": (
                _reachable_tiles(battle, selected, occupied, allied_slots)
                if selected is not None and clear_visibility
                else None
            ),
        }
    )


def _reachable_tiles(
    battle: BattleState,
    unit: UnitState,
    occupied: dict[tuple[int, int], UnitState],
    allied_slots: set[int],
) -> tuple[ReachableTile, ...] | None:
    """Find minimum-cost paths under the observed weather and CO rules."""
    profile = UNIT_PROFILES.get(unit.unit_type)
    context = observed_rule_context(battle, unit.army_slot)
    weather = battle.weather.value
    if (
        profile is None
        or context is None
        or battle.weather.status is not ValueStatus.AVAILABLE
        or weather is None
    ):
        return None
    limit = min(context.unit_limits(unit.unit_type)[0], unit.fuel)
    terrain = {
        (tile.x, tile.y): movement_cost(
            tile.terrain_class, profile.movement_type, weather, context=context
        )
        for tile in battle.map.tiles
        if tile.terrain_class in TERRAIN_NAMES
    }
    capture_tiles = {
        (prop.x, prop.y)
        for prop in battle.properties
        if unit.unit_type in CAPTURE_UNIT_TYPES
        and prop.terrain_class in CAPTURABLE_TERRAINS
        and prop.owner_slot not in allied_slots
    }
    start = (unit.x, unit.y)
    best = {start: 0}
    queue: list[tuple[int, tuple[int, int], tuple[Coordinate, ...]]] = [(0, start, ())]
    destinations = []
    while queue:
        cost, tile, path = heappop(queue)
        if cost != best[tile]:
            continue
        if tile not in occupied or tile == start and tile in capture_tiles:
            destinations.append(
                ReachableTile(
                    tile=Coordinate(x=tile[0], y=tile[1]),
                    path=path,
                    can_capture=tile in capture_tiles,
                )
            )
        x, y = tile
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            step_cost = terrain.get(neighbor)
            if step_cost is None:
                continue
            occupant = occupied.get(neighbor)
            if occupant is not None and occupant.army_slot not in allied_slots:
                continue
            new_cost = cost + step_cost
            if new_cost <= limit and new_cost < best.get(neighbor, limit + 1):
                best[neighbor] = new_cost
                step = Coordinate(x=neighbor[0], y=neighbor[1])
                heappush(queue, (new_cost, neighbor, (*path, step)))
    return tuple(destinations)
