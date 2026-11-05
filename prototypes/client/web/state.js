export const MATCH_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function validateState(value) {
  const summary = value?.summary,
    observation = value?.observation;
  if (value?.contract_version !== 1 || summary?.contract_version !== 1)
    throw new Error("Unsupported API contract version; expected version 1.");
  if (
    !summary ||
    typeof summary.match_id !== "string" ||
    !MATCH_ID.test(summary.match_id) ||
    !Number.isSafeInteger(summary.revision) ||
    summary.revision < 0 ||
    typeof value.settled !== "boolean"
  )
    throw new Error(
      "Expected a versioned StateResponse with summary, settled, and observation.",
    );
  if (observation !== null) {
    if (
      observation?.schema_version !== 1 ||
      observation.game_state?.schema_version !== 4
    )
      throw new Error(
        "Unsupported observation schema. Expected match schema 1 and game-state schema 4.",
      );
    if (
      observation.match_id !== summary.match_id ||
      observation.revision !== summary.revision
    )
      throw new Error(
        "Snapshot summary and observation do not identify the same boundary.",
      );
    const data = observation.game_state.battle;
    if (!["available", "unavailable", "unknown"].includes(data?.status))
      throw new Error("Invalid battle observation.");
    if (data.status === "available") {
      const b = data.value,
        m = b?.map;
      if (
        !m ||
        !Number.isInteger(m.width) ||
        !Number.isInteger(m.height) ||
        m.width < 1 ||
        m.height < 1 ||
        m.width > 128 ||
        m.height > 128 ||
        !Array.isArray(m.tiles) ||
        m.tiles.length !== m.width * m.height ||
        !Array.isArray(b.units) ||
        b.units.length > 4096 ||
        !Array.isArray(b.players) ||
        b.players.length > 8
      )
        throw new Error("Invalid or oversized map, units, or players.");
      const seen = new Set();
      for (const tile of m.tiles) {
        if (
          !tile ||
          !Number.isInteger(tile.x) ||
          !Number.isInteger(tile.y) ||
          tile.x < 0 ||
          tile.y < 0 ||
          tile.x >= m.width ||
          tile.y >= m.height ||
          !Number.isInteger(tile.terrain_class) ||
          !Number.isInteger(tile.owner_slot)
        )
          throw new Error("Invalid map tile.");
        seen.add(`${tile.x},${tile.y}`);
      }
      if (seen.size !== m.tiles.length) throw new Error("Duplicate map tiles.");
      if (
        !b.units.every(
          (u) =>
            u &&
            Number.isInteger(u.reference) &&
            Number.isInteger(u.x) &&
            Number.isInteger(u.y) &&
            Number.isInteger(u.unit_type) &&
            Number.isInteger(u.army_slot),
        ) ||
        !b.players.every((p) => p && Number.isInteger(p.slot))
      )
        throw new Error("Invalid units or players.");
    }
  }
  return value;
}
