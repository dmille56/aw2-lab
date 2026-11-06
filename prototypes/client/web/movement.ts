import catalog from "./catalog.json";
import type { BattleState, UnitState } from "./state";
import type { Position } from "./Board";

interface MovementContext {
  weather_variants: Record<string, string>;
  movement_bonuses: Record<number, number>;
}
const contexts: Record<string, MovementContext> = catalog.movement.contexts;
const costs: Record<string, Record<number, (number | null)[]>> = catalog
  .movement.costs;
const units: Record<
  number,
  { name: string; movement_type: string; movement: number }
> = catalog.units;
const types: Record<string, number> = catalog.movement.types;
export interface MovementReport {
  cost: number;
  allowance: number | null;
  error: string | null;
  endpointError: string | null;
}

export interface MovementReach {
  destinations: Set<string>;
  alliedTransit: Set<string>;
}

/** Return observed legal drop tiles adjacent to a carrier's planned destination. */
export function unloadDropTiles(
  battle: BattleState,
  carrier: UnitState,
  cargo: UnitState,
  carrierDestination: Position,
): Position[] {
  const profile = units[cargo.unit_type];
  const player = battle.players.find((item) => item.slot === cargo.army_slot);
  if (
    !profile ||
    battle.co_effects_enabled.status !== "available" ||
    battle.weather.status !== "available" ||
    battle.weather.value === null
  )
    return [];
  const context =
    contexts[
      battle.co_effects_enabled.value === false
        ? "baseline"
        : `${player?.co_id}:${player?.active_power}`
    ];
  if (!context) return [];
  const table = costs[context.weather_variants[battle.weather.value]];
  const movementType = types[profile.movement_type];
  if (!table || movementType === undefined) return [];
  const occupied = new Set(
    battle.units
      .filter((unit) => !unit.embarked && unit.reference !== carrier.reference)
      .map((unit) => `${unit.x},${unit.y}`),
  );
  return battle.map.tiles
    .filter((tile) => {
      const adjacent =
        Math.abs(tile.x - carrierDestination.x) +
          Math.abs(tile.y - carrierDestination.y) ===
        1;
      const terrainCost = table[tile.terrain_class]?.[movementType];
      return (
        adjacent &&
        !occupied.has(`${tile.x},${tile.y}`) &&
        terrainCost !== undefined &&
        terrainCost !== null
      );
    })
    .map(({ x, y }) => ({ x, y }))
    .sort((a, b) => a.y - b.y || a.x - b.x);
}

/** Calculate observed reachable tiles with Dijkstra, allowing allies as transit only. */
export function movementReach(
  battle: BattleState,
  unit: UnitState,
): MovementReach {
  const result: MovementReach = {
    destinations: new Set(),
    alliedTransit: new Set(),
  };
  const profile = units[unit.unit_type];
  if (
    !profile ||
    battle.co_effects_enabled.status !== "available" ||
    battle.fog_enabled.status !== "available" ||
    battle.fog_enabled.value
  )
    return result;
  const player = battle.players.find((item) => item.slot === unit.army_slot);
  const effects = battle.co_effects_enabled.value;
  const context =
    contexts[
      effects === false
        ? "baseline"
        : `${player?.co_id}:${player?.active_power}`
    ];
  if (
    !context ||
    battle.weather.status !== "available" ||
    battle.weather.value === null
  )
    return result;
  const table = costs[context.weather_variants[battle.weather.value]];
  if (!table) return result;
  const allowance =
    profile.movement + (context.movement_bonuses[unit.unit_type] ?? 0);
  const terrain = new Map(
    battle.map.tiles.map((tile) => [`${tile.x},${tile.y}`, tile]),
  );
  const alliedSlots = new Set(
    battle.players
      .filter((other) => player && other.team_id === player.team_id)
      .map((other) => other.slot),
  );
  alliedSlots.add(unit.army_slot);
  const occupants = new Map(
    battle.units
      .filter((other) => !other.embarked && other.reference !== unit.reference)
      .map((other) => [`${other.x},${other.y}`, other]),
  );
  const distances = new Map<string, number>([[`${unit.x},${unit.y}`, 0]]);
  const maxCost = Math.min(allowance, unit.fuel);
  const buckets: { x: number; y: number }[][] = Array.from(
    { length: maxCost + 1 },
    () => [],
  );
  buckets[0].push({ x: unit.x, y: unit.y });
  for (let currentCost = 0; currentCost <= maxCost; currentCost++) {
    while (buckets[currentCost].length) {
      const current = buckets[currentCost].pop()!;
      const currentKey = `${current.x},${current.y}`;
      if (distances.get(currentKey) !== currentCost) continue;
      for (const [dx, dy] of [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ]) {
        const x = current.x + dx;
        const y = current.y + dy;
        const key = `${x},${y}`;
        const tile = terrain.get(key);
        if (!tile) continue;
        const occupant = occupants.get(key);
        if (occupant && !alliedSlots.has(occupant.army_slot)) continue;
        const cost = table[tile.terrain_class]?.[types[profile.movement_type]];
        if (cost === undefined || cost === null) continue;
        const total = currentCost + cost;
        if (total > allowance || total > unit.fuel) continue;
        if (total >= (distances.get(key) ?? Infinity)) continue;
        distances.set(key, total);
        buckets[total].push({ x, y });
      }
    }
  }
  for (const [key] of distances) {
    if (key === `${unit.x},${unit.y}`) continue;
    const occupant = occupants.get(key);
    if (occupant) result.alliedTransit.add(key);
    else result.destinations.add(key);
  }
  return result;
}

/** Validate observed rules only; hidden blockers remain the executor's responsibility. */
export function validateMovement(
  battle: BattleState,
  unit: UnitState,
  path: Position[],
): MovementReport {
  const report: MovementReport = {
    cost: 0,
    allowance: null,
    error: null,
    endpointError: null,
  };
  const reject = (error: string) => ({ ...report, error });
  const profile = units[unit.unit_type];
  if (!profile) return reject("Movement rules for this unit are unavailable.");
  const player = battle.players.find(
    (player) => player.slot === unit.army_slot,
  );
  const effects = battle.co_effects_enabled;
  if (effects.status !== "available")
    return reject(
      "Movement validation requires an observed CO effects setting.",
    );
  const context =
    contexts[
      effects.value === false
        ? "baseline"
        : `${player?.co_id}:${player?.active_power}`
    ];
  if (!context)
    return reject(
      "Movement rules for this CO and active power are unavailable.",
    );
  const allowance =
    profile.movement + (context.movement_bonuses[unit.unit_type] ?? 0);
  report.allowance = allowance;
  if (battle.weather.status !== "available" || battle.weather.value === null)
    return reject("Movement validation requires observed weather.");
  const table = costs[context.weather_variants[battle.weather.value]];
  if (!table) return reject("Movement costs for this weather are unavailable.");
  let previous: Position = unit;
  const terrain = new Map(
    battle.map.tiles.map((tile) => [`${tile.x},${tile.y}`, tile]),
  );
  const alliedSlots = new Set(
    battle.players
      .filter((other) => player && other.team_id === player.team_id)
      .map((other) => other.slot),
  );
  alliedSlots.add(unit.army_slot);
  const occupants = new Map(
    battle.units
      .filter((other) => !other.embarked && other.reference !== unit.reference)
      .map((other) => [`${other.x},${other.y}`, other]),
  );
  for (const point of path) {
    if (Math.abs(point.x - previous.x) + Math.abs(point.y - previous.y) !== 1)
      return reject(
        "Each movement step must be adjacent to the previous tile.",
      );
    const key = `${point.x},${point.y}`;
    const tile = terrain.get(key);
    if (!tile)
      return reject("Movement requires an observed tile inside the map.");
    const cost = table[tile.terrain_class]?.[types[profile.movement_type]];
    if (cost === undefined)
      return reject("Movement costs for this terrain are unavailable.");
    if (cost === null)
      return reject(
        `${profile.name} cannot enter ${catalog.terrain[String(tile.terrain_class) as keyof typeof catalog.terrain] ?? "this terrain"}.`,
      );
    const occupant = occupants.get(key);
    if (occupant && !alliedSlots.has(occupant.army_slot))
      return reject("An observed enemy unit blocks this route.");
    report.cost += cost;
    if (report.cost > allowance)
      return reject(
        `Route costs ${report.cost} movement points; this unit has ${allowance}.`,
      );
    if (report.cost > unit.fuel)
      return reject(
        `Route costs ${report.cost} fuel; this unit has ${unit.fuel}.`,
      );
    previous = point;
  }
  const destination = path.at(-1);
  if (destination && occupants.has(`${destination.x},${destination.y}`))
    report.endpointError =
      "An allied unit occupies this tile. You can move through it; choose an empty tile to finish.";
  return report;
}
