import validateSchema from "./generated/validate-state.js";
import type { components } from "./generated/api";
export type StateResponse = components["schemas"]["StateResponse"];
export type BattleState = components["schemas"]["BattleState"];
export type UnitState = components["schemas"]["UnitState"];
export const MATCH_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};

export function validateState(value: unknown): StateResponse {
  const envelope = record(value),
    summary = record(envelope.summary),
    observation = record(envelope.observation);
  if (envelope.contract_version !== 1 || summary.contract_version !== 1)
    throw new Error("Unsupported API contract version; expected version 1.");
  if (
    envelope.observation !== null &&
    (observation.schema_version !== 1 ||
      record(observation.game_state).schema_version !== 4)
  )
    throw new Error(
      "Unsupported observation schema. Expected match schema 1 and game-state schema 4.",
    );
  if (!validateSchema(value))
    throw new Error(
      "Expected a valid versioned StateResponse with summary, settled, and observation.",
    );
  // The generated validator checks the full shared schema before this narrowing.
  const state = value as StateResponse;
  if (
    !MATCH_ID.test(state.summary.match_id) ||
    !Number.isSafeInteger(state.summary.revision) ||
    state.summary.revision < 0
  )
    throw new Error("Invalid match identity or revision.");
  const obs = state.observation;
  if (obs) {
    if (
      obs.match_id !== state.summary.match_id ||
      obs.revision !== state.summary.revision
    )
      throw new Error(
        "Snapshot summary and observation do not identify the same boundary.",
      );
    const data = obs.game_state.battle;
    if (data.status === "available") {
      const b = data.value;
      if (!b) throw new Error("Available battle observation has no value.");
      const m = b.map;
      if (
        m.width < 1 ||
        m.height < 1 ||
        m.width > 128 ||
        m.height > 128 ||
        m.tiles.length !== m.width * m.height ||
        b.units.length > 4096 ||
        b.players.length > 8
      )
        throw new Error("Invalid or oversized map, units, or players.");
      const seen = new Set<string>();
      for (const tile of m.tiles) {
        if (tile.x < 0 || tile.y < 0 || tile.x >= m.width || tile.y >= m.height)
          throw new Error("Invalid map tile.");
        seen.add(`${tile.x},${tile.y}`);
      }
      if (seen.size !== m.tiles.length) throw new Error("Duplicate map tiles.");
    }
  }
  return state;
}
