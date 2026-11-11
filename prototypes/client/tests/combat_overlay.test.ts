import { describe, expect, it } from "vitest";
import {
  enemyThreatCoverage,
  selectedAttackCoverage,
  attackTargets,
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
  it("filters targets by endpoint, alliance, cargo, and weapon compatibility", () => {
    const battle = battleFixture();
    const [unit, enemy] = battle.units;
    expect(attackTargets(battle, unit, [])).toEqual([]);
    expect(attackTargets(battle, unit, [{ x: 1, y: 0 }])).toEqual([enemy]);
    enemy.unit_type = 16;
    expect(attackTargets(battle, unit, [{ x: 1, y: 0 }])).toEqual([]);
    enemy.unit_type = 1;
    enemy.embarked = true;
    expect(attackTargets(battle, unit, [{ x: 1, y: 0 }])).toEqual([]);
    enemy.embarked = false;
    battle.players[1].team_id = battle.players[0].team_id;
    expect(attackTargets(battle, unit, [{ x: 1, y: 0 }])).toEqual([]);
  });

  it("respects ammunition, secondary weapons, and submerged target compatibility", () => {
    const battle = battleFixture();
    const [unit, enemy] = battle.units;
    unit.unit_type = 3;
    enemy.x = 1;
    enemy.y = 0;
    enemy.unit_type = 24;
    unit.ammo = 0;
    expect(attackTargets(battle, unit, [])).toEqual([]);
    unit.ammo = 1;
    expect(attackTargets(battle, unit, [])).toEqual([enemy]);
    unit.ammo = 0;
    enemy.unit_type = 1;
    expect(attackTargets(battle, unit, [])).toEqual([enemy]);
    unit.unit_type = 22;
    unit.ammo = 1;
    enemy.unit_type = 24;
    enemy.submerged = true;
    expect(attackTargets(battle, unit, [])).toEqual([enemy]);
    unit.unit_type = 3;
    expect(attackTargets(battle, unit, [])).toEqual([]);
  });

  it("uses indirect minimum range and CO bonuses, and forbids moving then firing", () => {
    const battle = battleFixture();
    const [unit, enemy] = battle.units;
    unit.unit_type = 10;
    unit.ammo = 1;
    enemy.x = 0;
    enemy.y = 4;
    expect(attackTargets(battle, unit, [])).toEqual([]);
    battle.co_effects_enabled.value = true;
    battle.players[0].co_id = 5;
    expect(attackTargets(battle, unit, [])).toEqual([enemy]);
    expect(attackTargets(battle, unit, [{ x: 0, y: 1 }])).toEqual([]);
    enemy.y = 1;
    expect(attackTargets(battle, unit, [])).toEqual([]);
  });
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
