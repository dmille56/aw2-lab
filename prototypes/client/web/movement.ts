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
