import { describe, expect, it } from "vitest";
import {
  movementReach,
  movementRoute,
  validateMovement,
} from "../web/movement";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";

function scenario(unitType = 1, terrainClass = 1) {
  const battle = validateState(structuredClone(fixture)).observation!.game_state
    .battle.value!;
  battle.co_effects_enabled = { status: "available", value: true, reasons: [] };
  const unit = battle.units[0];
  unit.unit_type = unitType;
  battle.units = [unit];
  battle.map.width = 8;
  battle.map.height = 2;
  battle.map.tiles = Array.from({ length: 16 }, (_, index) => ({
    x: index % 8,
    y: Math.floor(index / 8),
    terrain_class: terrainClass,
    graphical_tile_id: 1,
    owner_slot: 0,
  }));
  return { battle, unit };
}
const route = (length: number) =>
  Array.from({ length }, (_, index) => ({ x: index + 1, y: 0 }));
describe("observed movement validation", () => {
  it("limits total movement cost, using the selected unit's terrain costs", () => {
    const { battle, unit } = scenario();
    expect(validateMovement(battle, unit, route(3))).toMatchObject({
      cost: 3,
      allowance: 3,
      error: null,
    });
    expect(validateMovement(battle, unit, route(4)).error).toContain(
      "movement points",
    );
    battle.map.tiles.forEach((tile) => {
      tile.terrain_class = 3;
    });
    expect(validateMovement(battle, unit, route(2)).error).toContain(
      "movement points",
    );
    unit.unit_type = 2;
    expect(validateMovement(battle, unit, route(2))).toMatchObject({
      cost: 2,
      allowance: 2,
      error: null,
    });
  });
  it("marks reachable destinations and allied transit without marking enemy blockers", () => {
    const { battle, unit } = scenario();
    battle.map.width = 4;
    battle.map.height = 2;
    battle.map.tiles = Array.from({ length: 8 }, (_, index) => ({
      x: index % 4,
      y: Math.floor(index / 4),
      terrain_class: 1,
      graphical_tile_id: 1,
      owner_slot: 0,
    }));
    const ally = { ...unit, reference: 2, unit_slot: 2, x: 1, y: 0 };
    const enemy = {
      ...unit,
      reference: 3,
      army_slot: 2,
      unit_slot: 1,
      x: 3,
      y: 0,
    };
    battle.units.push(ally, enemy);
    const reach = movementReach(battle, unit);
    expect(reach.alliedTransit).toContain("1,0");
    expect(reach.destinations).toContain("2,0");
    expect(reach.destinations).not.toContain("3,0");
    expect(reach.destinations).not.toContain("1,0");
  });
  it("does not infer movement coverage from full unit coordinates under fog", () => {
    const { battle, unit } = scenario();
    battle.fog_enabled = { status: "available", value: true, reasons: [] };
    expect(movementReach(battle, unit)).toEqual({
      destinations: new Set(),
      alliedTransit: new Set(),
    });
  });
  it("rejects sea for land units and land for ships, while aircraft can cross sea", () => {
    const { battle, unit } = scenario(5, 7);
    expect(validateMovement(battle, unit, route(1)).error).toContain(
      "cannot enter Sea",
    );
    unit.unit_type = 16;
    expect(validateMovement(battle, unit, route(1)).error).toBeNull();
    unit.unit_type = 21;
    battle.map.tiles.forEach((tile) => {
      tile.terrain_class = 1;
    });
    expect(validateMovement(battle, unit, route(1)).error).toContain(
      "cannot enter Plain",
    );
  });
  it("accounts for remaining fuel, weather and CO powers, and effects being disabled", () => {
    const { battle, unit } = scenario();
    unit.fuel = 2;
    expect(validateMovement(battle, unit, route(3)).error).toContain("fuel");
    unit.fuel = 99;
    battle.players[0].active_power = 2;
    expect(validateMovement(battle, unit, route(4))).toMatchObject({
      allowance: 4,
      error: null,
    });
    battle.co_effects_enabled.value = false;
    expect(validateMovement(battle, unit, route(4)).error).toContain(
      "movement points",
    );
    battle.weather.value = "snow";
    expect(validateMovement(battle, unit, route(2)).error).toContain(
      "movement points",
    );
    battle.co_effects_enabled.value = true;
    battle.players[0].co_id = 3;
    battle.players[0].active_power = 0;
    expect(validateMovement(battle, unit, route(3))).toMatchObject({
      cost: 3,
      error: null,
    });
  });
  it("blocks observed enemies but allows friendly passage without accepting an occupied endpoint", () => {
    const { battle, unit } = scenario();
    const other = { ...unit, reference: 2, unit_slot: 1, x: 1, y: 0 };
    battle.units.push(other);
    expect(validateMovement(battle, unit, route(1)).endpointError).toContain(
      "occupies",
    );
    expect(validateMovement(battle, unit, route(2))).toMatchObject({
      error: null,
      endpointError: null,
    });
    other.army_slot = 2;
    expect(validateMovement(battle, unit, route(2)).error).toContain("enemy");
    battle.players[1].team_id = battle.players[0].team_id;
    const alliedEndpoint = validateMovement(battle, unit, route(1));
    expect(alliedEndpoint.error).toBeNull();
    expect(alliedEndpoint.endpointError).toContain("allied");
    expect(validateMovement(battle, unit, route(2))).toMatchObject({
      error: null,
      endpointError: null,
    });
    battle.players[1].team_id = battle.players[0].team_id + 1;
    other.embarked = true;
    expect(validateMovement(battle, unit, route(2)).error).toBeNull();
  });
  it("refuses to guess missing rules, invalid coordinates or discontinuous routes", () => {
    const { battle, unit } = scenario();
    expect(validateMovement(battle, unit, [{ x: 2, y: 0 }]).error).toContain(
      "adjacent",
    );
    expect(validateMovement(battle, unit, [{ x: -1, y: 0 }]).error).toContain(
      "inside the map",
    );
    battle.weather = {
      status: "unknown",
      value: null,
      reasons: ["Not observed"],
    };
    expect(validateMovement(battle, unit, route(1)).error).toContain(
      "observed weather",
    );
    battle.weather = { status: "available", value: "clear", reasons: [] };
    battle.players[0].co_id = 99;
    expect(validateMovement(battle, unit, route(1)).error).toContain("CO");
  });
});

describe("destination routes", () => {
  it("reconstructs a minimum-cost path and stable ties without the origin", () => {
    const { battle, unit } = scenario();
    const path = movementRoute(battle, unit, { x: 1, y: 1 });
    expect(path).toHaveLength(2);
    expect(path).toEqual(movementRoute(battle, unit, { x: 1, y: 1 }));
    expect(path?.at(-1)).toEqual({ x: 1, y: 1 });
    expect(validateMovement(battle, unit, path!)).toMatchObject({
      cost: 2,
      error: null,
    });
    expect(movementRoute(battle, unit, unit)).toEqual([]);
  });
  it("uses a cheaper detour and honors fuel, blockers, and unavailable rules", () => {
    const { battle, unit } = scenario(5);
    battle.map.tiles.find((t) => t.x === 1 && t.y === 0)!.terrain_class = 3;
    const path = movementRoute(battle, unit, { x: 2, y: 0 });
    expect(path).toHaveLength(4);
    expect(validateMovement(battle, unit, path!).error).toBeNull();
    unit.fuel = 3;
    expect(movementRoute(battle, unit, { x: 2, y: 0 })).toBeNull();
    unit.fuel = 99;
    battle.fog_enabled.value = true;
    expect(movementRoute(battle, unit, { x: 2, y: 0 })).toBeNull();
  });
  it("allows allied transit while leaving endpoint action checks to the caller", () => {
    const { battle, unit } = scenario();
    battle.units.push({
      ...unit,
      reference: 2,
      x: 1,
      y: 0,
      used_this_turn: true,
    });
    expect(movementRoute(battle, unit, { x: 2, y: 0 })).toEqual([
      { x: 1, y: 0 },
      { x: 2, y: 0 },
    ]);
    expect(
      validateMovement(
        battle,
        unit,
        movementRoute(battle, unit, { x: 1, y: 0 })!,
      ).endpointError,
    ).not.toBeNull();
    battle.units[1].army_slot = 2;
    expect(movementRoute(battle, unit, { x: 1, y: 0 })).toBeNull();
  });
});
