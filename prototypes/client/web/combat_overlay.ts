import catalogData from "./catalog.json";
import { movementReach } from "./movement";
import type { BattleState, UnitState } from "./state";
import type { Position } from "./Board";

const catalog: {
  units: Record<
    number,
    {
      minimum_range: number;
      maximum_range: number;
      ammo_capacity: number;
      primary_targets: number[];
      secondary_targets: number[];
    }
  >;
} = catalogData;
const key = (position: Position) => `${position.x},${position.y}`;
const canFire = (unit: UnitState) => {
  const profile = catalog.units[unit.unit_type];
  if (!profile || profile.maximum_range < 1) return false;
  if (profile.ammo_capacity === 0 || unit.ammo > 0) return true;
  return profile.secondary_targets.length > 0;
};
function addRange(
  cells: Set<string>,
  battle: BattleState,
  unit: UnitState,
  origin: Position,
) {
  const profile = catalog.units[unit.unit_type];
  if (!profile || !canFire(unit)) return;
  for (const tile of battle.map.tiles) {
    const distance = Math.abs(tile.x - origin.x) + Math.abs(tile.y - origin.y);
    if (
      distance >= profile.minimum_range &&
      distance <= profile.maximum_range
    ) {
      cells.add(key(tile));
    }
  }
}

export function selectedAttackCoverage(
  battle: BattleState,
  unit: UnitState,
  route: Position[],
): Set<string> {
  const result = new Set<string>();
  const profile = catalog.units[unit.unit_type];
  if (!profile || !canFire(unit)) return result;
  if (profile.minimum_range > 1) {
    if (route.length) return result;
    addRange(result, battle, unit, unit);
    return result;
  }
  if (route.length) {
    addRange(result, battle, unit, route.at(-1)!);
    return result;
  }
  const reach = movementReach(battle, unit);
  addRange(result, battle, unit, unit);
  for (const cell of reach.destinations) {
    const [x, y] = cell.split(",").map(Number);
    addRange(result, battle, unit, { x, y });
  }
  return result;
}

export function enemyThreatCoverage(battle: BattleState, yourSlot: number) {
  const result = new Set<string>();
  if (battle.fog_enabled.status !== "available" || battle.fog_enabled.value)
    return result;
  const player = battle.players.find((item) => item.slot === yourSlot);
  const allies = new Set(
    battle.players
      .filter((item) => player && item.team_id === player.team_id)
      .map((item) => item.slot),
  );
  for (const unit of battle.units) {
    if (unit.embarked || allies.has(unit.army_slot)) continue;
    const profile = catalog.units[unit.unit_type];
    if (!profile || !canFire(unit)) continue;
    if (profile.minimum_range > 1) {
      addRange(result, battle, unit, unit);
      continue;
    }
    addRange(result, battle, unit, unit);
    for (const cell of movementReach(battle, unit).destinations) {
      const [x, y] = cell.split(",").map(Number);
      addRange(result, battle, unit, { x, y });
    }
  }
  return result;
}

export function potentialAttackDescription(unit: UnitState) {
  const profile = catalog.units[unit.unit_type];
  if (!profile) return "Attack rules unavailable.";
  if (!canFire(unit)) return "No available ammunition for an attack.";
  return profile.ammo_capacity > 0 && unit.ammo === 0
    ? "Only unlimited secondary weapons are available. Their target compatibility still applies."
    : "Range coverage shows possible firing tiles; terrain, target compatibility, and combat outcome still apply.";
}
