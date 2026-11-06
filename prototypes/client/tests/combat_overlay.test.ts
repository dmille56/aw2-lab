import { describe, expect, it } from "vitest";
import {
  enemyThreatCoverage,
  selectedAttackCoverage,
} from "../web/combat_overlay";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";

function battleFixture() {
  const battle = validateState(structuredClone(fixture)).observation!.game_state
    .battle.value!;
  battle.co_effects_enabled = {
    status: "available",
    value: false,
    reasons: [],
  };
  battle.map.width = 8;
  battle.map.height = 8;
  battle.map.tiles = Array.from({ length: 64 }, (_, index) => ({
    x: index % 8,
    y: Math.floor(index / 8),
    terrain_class: 1,
    graphical_tile_id: 1,
    owner_slot: 0,
  }));
  return battle;
}

describe("gameplay overlay coverage", () => {
  it("shows direct attacks from reachable firing positions and then the planned endpoint", () => {
    const battle = battleFixture();
    const unit = battle.units[0];
    expect(selectedAttackCoverage(battle, unit, [])).toContain("4,0");
    expect(selectedAttackCoverage(battle, unit, [{ x: 1, y: 0 }])).toContain(
      "2,0",
    );
    expect(
      selectedAttackCoverage(battle, unit, [{ x: 1, y: 0 }]),
    ).not.toContain("4,0");
  });

  it("keeps indirect range at the current tile and suppresses unloaded attacks", () => {
    const battle = battleFixture();
    const unit = battle.units[0];
    unit.unit_type = 10;
    unit.x = 3;
    unit.y = 3;
    unit.ammo = 0;
    expect(selectedAttackCoverage(battle, unit, [])).toEqual(new Set());
    unit.ammo = 1;
    expect(selectedAttackCoverage(battle, unit, [])).toContain("3,5");
    expect(selectedAttackCoverage(battle, unit, [{ x: 3, y: 4 }])).toEqual(
      new Set(),
    );
    expect(selectedAttackCoverage(battle, unit, [])).not.toContain("3,7");
  });

  it("computes enemy threat from observed units and distinguishes teams", () => {
    const battle = battleFixture();
    const [ownUnit, enemy] = battle.units;
    battle.units = [ownUnit];
    expect(enemyThreatCoverage(battle, 1)).toEqual(new Set());
    battle.units.push(enemy);
    const threats = enemyThreatCoverage(battle, 1);
    expect(threats.has("0,0")).toBe(true);
    expect(threats.has("0,1")).toBe(true);
    expect(threats.has("1,0")).toBe(true);
  });

  it("hides enemy threat coverage when fog visibility is not represented", () => {
    const battle = battleFixture();
    battle.fog_enabled = { status: "available", value: true, reasons: [] };
    expect(enemyThreatCoverage(battle, 1)).toEqual(new Set());
    battle.fog_enabled = {
      status: "unknown",
      value: null,
      reasons: ["Visibility is unavailable"],
    };
    expect(enemyThreatCoverage(battle, 1)).toEqual(new Set());
  });
});
