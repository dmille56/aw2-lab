import { describe, expect, it } from "vitest";
import { validateMovement } from "../web/movement";
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
