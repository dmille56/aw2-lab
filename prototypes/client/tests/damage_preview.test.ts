import { describe, it, expect } from "vitest";
import { estimateAttackDamage } from "../web/damage_preview";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";
function scenario() {
  const battle = validateState(structuredClone(fixture)).observation!.game_state
    .battle.value!;
  const [attacker, defender] = battle.units;
  defender.y = 0;
  battle.co_effects_enabled = {
    status: "available",
    value: false,
    reasons: [],
  };
  return { battle, attacker, defender };
}
describe("AW2 damage preview", () => {
  it("shows native no-luck forecasts and actual luck intervals", () => {
    const { battle, attacker, defender } = scenario();
    expect(estimateAttackDamage(battle, attacker, defender, [])).toEqual({
      status: "available",
      forecast: 49,
      minimum: 49,
      maximum: 57,
    });
    battle.map.tiles.find((t) => t.x === 1 && t.y === 0)!.terrain_class = 6;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toEqual({
      status: "available",
      forecast: 38,
      minimum: 38,
      maximum: 44,
    });
  });
  it("uses rounded unit HP and applies native integer truncation", () => {
    const { battle, attacker, defender } = scenario();
    attacker.internal_health = 51;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toEqual({
      status: "available",
      forecast: 29,
      minimum: 29,
      maximum: 34,
    });
    battle.map.tiles.find((t) => t.x === 1 && t.y === 0)!.terrain_class = 6;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toEqual({
      status: "available",
      forecast: 22,
      minimum: 23,
      maximum: 26,
    });
  });
  it("chooses the effective weapon and falls back when primary ammo is empty", () => {
    const { battle, attacker, defender } = scenario();
    attacker.unit_type = 2;
    attacker.ammo = 3;
    defender.unit_type = 5;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 49,
    });
    attacker.ammo = 0;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 5,
    });
    attacker.unit_type = 5;
    attacker.ammo = 9;
    defender.unit_type = 1;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 67,
    });
  });
  it("includes CO class bonuses and observed universal modifiers", () => {
    const { battle, attacker, defender } = scenario();
    battle.co_effects_enabled.value = true;
    battle.players[0].co_id = 2;
    battle.players[1].co_id = 1;
    attacker.unit_type = defender.unit_type = 5;
    attacker.ammo = 9;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 59,
    });
    battle.players[1].defense_bonus = {
      status: "available",
      value: 10,
      reasons: [],
    };
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 52,
    });
  });
  it("uses planned terrain for Lash and ignores terrain for aircraft", () => {
    const { battle, attacker, defender } = scenario();
    battle.co_effects_enabled.value = true;
    battle.players[0].co_id = 12;
    battle.players[1].co_id = 1;
    battle.map.tiles.find((t) => t.x === 0 && t.y === 0)!.terrain_class = 4;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 59,
    });
    battle.players[0].co_id = 1;
    attacker.unit_type = 14;
    attacker.ammo = 9;
    defender.unit_type = 19;
    battle.map.tiles.find((t) => t.x === 1 && t.y === 0)!.terrain_class = 3;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "available",
      forecast: 120,
    });
  });
  it("reflects bad luck and declares missing data or counter-first powers unavailable", () => {
    const { battle, attacker, defender } = scenario();
    battle.co_effects_enabled.value = true;
    battle.players[0].co_id = 11;
    battle.players[1].co_id = 1;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toEqual({
      status: "available",
      forecast: 49,
      minimum: 41,
      maximum: 62,
    });
    battle.players[1].co_id = 7;
    battle.players[1].active_power = 2;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "unavailable",
    });
    battle.players[1].co_id = 1;
    battle.players[1].active_power = 0;
    delete (battle.players[0] as Partial<(typeof battle.players)[0]>)
      .attack_bonus;
    expect(estimateAttackDamage(battle, attacker, defender, [])).toMatchObject({
      status: "unavailable",
    });
  });
});

it("accepts legacy snapshots without optional combat observations and reports an unavailable preview", () => {
  const legacy = structuredClone(fixture);
  const player = legacy.observation.game_state.battle.value
    .players[0] as Partial<
    (typeof legacy.observation.game_state.battle.value.players)[0]
  >;
  delete player.attack_bonus;
  delete player.defense_bonus;
  const battle = validateState(legacy).observation!.game_state.battle.value!;
  battle.units[1].y = 0;
  expect(
    estimateAttackDamage(battle, battle.units[0], battle.units[1], []),
  ).toMatchObject({ status: "unavailable" });
});
