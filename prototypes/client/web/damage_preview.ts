import catalog from "./catalog.json";
import { attackTargets } from "./combat_overlay";
import type { Position } from "./Board";
import type { BattleState, UnitState } from "./state";

type Profile = {
  luck: number;
  bad_luck: number;
  flags: number;
  bonuses: Record<number, number[]>;
};
const combat = catalog.combat as {
  base_damage: Record<
    number,
    { primary: Record<number, number>; secondary: Record<number, number> }
  >;
  terrain_stars: number[];
  co_profiles: Record<string, Profile>;
};
export type DamageEstimate =
  | { status: "available"; forecast: number; minimum: number; maximum: number }
  | { status: "unavailable"; reason: string };
const unavailable = (reason: string): DamageEstimate => ({
  status: "unavailable",
  reason,
});
const displayedHP = (unit: UnitState) => Math.ceil(unit.internal_health / 10);
const unitData = catalog.units as Record<
  number,
  { movement_type: string; maximum_range: number }
>;

/** Native US rev-0 0x08024ABC/0x08024C58/0x08024DDC/0x08024E60. */
export function estimateAttackDamage(
  battle: BattleState,
  attacker: UnitState,
  defender: UnitState,
  path: Position[],
): DamageEstimate {
  if (
    !attackTargets(battle, attacker, path).some(
      (unit) => unit.reference === defender.reference,
    )
  )
    return unavailable(
      "This target cannot be attacked from the planned position.",
    );
  if (battle.fog_enabled.status !== "available" || battle.fog_enabled.value)
    return unavailable(
      "Target visibility is not verified while fog is enabled or unknown.",
    );
  if (battle.co_effects_enabled.status !== "available")
    return unavailable("The CO effects setting is unknown.");
  const owner = battle.players.find((p) => p.slot === attacker.army_slot);
  const enemy = battle.players.find((p) => p.slot === defender.army_slot);
  if (
    !owner ||
    !enemy ||
    owner.attack_bonus?.status !== "available" ||
    enemy.defense_bonus?.status !== "available" ||
    typeof owner.attack_bonus.value !== "number" ||
    typeof enemy.defense_bonus.value !== "number"
  )
    return unavailable(
      "Player combat bonuses were not observed in this snapshot.",
    );
  const enabled = battle.co_effects_enabled.value;
  const attacking = combat.co_profiles[`${owner.co_id}:${owner.active_power}`];
  const defending = combat.co_profiles[`${enemy.co_id}:${enemy.active_power}`];
  if (enabled && (!attacking || !defending))
    return unavailable("These CO/power modifiers are not verified.");
  const attackBonus = enabled ? attacking.bonuses[attacker.unit_type]?.[0] : 0;
  const defenseBonus = enabled ? defending.bonuses[defender.unit_type]?.[1] : 0;
  if (attackBonus === undefined || defenseBonus === undefined)
    return unavailable("These unit combat modifiers are not verified.");
  const origin = path.at(-1) ?? attacker;
  const terrain = (
    unit: UnitState,
    point: Position,
    flags: number,
  ): number | null => {
    if (unitData[unit.unit_type]?.movement_type === "AIR") return 0;
    const tile = battle.map.tiles.find(
      (t) => t.x === point.x && t.y === point.y,
    );
    const stars = tile ? combat.terrain_stars[tile.terrain_class] : undefined;
    return stars === undefined ? null : stars * (flags & 0x20 ? 2 : 1);
  };
  const attackFlags = enabled ? attacking.flags : 0;
  const defenseFlags = enabled ? defending.flags : 0;
  const attackStars = terrain(attacker, origin, attackFlags);
  const defenseStars = terrain(defender, defender, defenseFlags);
  if (attackStars === null || defenseStars === null)
    return unavailable("Terrain defense is not verified.");
  const chart = combat.base_damage[attacker.unit_type];
  const targetType =
    defender.unit_type === 24 && defender.submerged ? 25 : defender.unit_type;
  if (!chart) return unavailable("This weapon matchup is not verified.");
  const primary = attacker.ammo > 0 ? (chart.primary[targetType] ?? 0) : 0;
  const secondary = chart.secondary[targetType] ?? 0;
  const base = Math.max(primary, secondary);
  if (!base || displayedHP(attacker) < 1 || displayedHP(defender) < 1)
    return unavailable("No effective weapon or healthy attacker is available.");
  const reverse = combat.base_damage[defender.unit_type];
  const attackerType =
    attacker.unit_type === 24 && attacker.submerged ? 25 : attacker.unit_type;
  const canCounter =
    Math.abs(origin.x - defender.x) + Math.abs(origin.y - defender.y) === 1 &&
    unitData[defender.unit_type]?.maximum_range === 1 &&
    reverse &&
    ((defender.ammo > 0 && reverse.primary[attackerType]) ||
      reverse.secondary[attackerType]);
  if (defenseFlags & 4 && canCounter)
    return unavailable(
      "The defender's counter-first power changes your HP before this attack.",
    );
  // The cartridge floors class firepower, then applies global/Lash firepower.
  const classBase = Math.max(1, Math.floor((base * (100 + attackBonus)) / 100));
  const total = Math.floor(
    (classBase *
      (100 +
        owner.attack_bonus.value +
        (attackFlags & 0x40 ? attackStars * 10 : 0))) /
      100,
  );
  const defense =
    100 +
    defenseBonus +
    enemy.defense_bonus.value +
    defenseStars * displayedHP(defender);
  if (total < 0 || total > 32000 || defense < 0 || defense > 200)
    return unavailable("Combat modifiers exceed the verified forecast range.");
  const factor = 200 - defense;
  const hp = displayedHP(attacker);
  const good = enabled ? attacking.luck : 10;
  const bad = enabled ? attacking.bad_luck : 0;
  // Forecast: defense then HP. Actual damage: HP then defense, including luck.
  const actual = (luck: number) =>
    Math.floor(
      (Math.floor((Math.max(0, total + luck) * hp) / 10) * factor) / 100,
    );
  return {
    status: "available",
    forecast: Math.min(
      999,
      Math.floor((Math.floor((total * factor) / 100) * hp) / 10),
    ),
    minimum: actual(-Math.max(0, bad - 1)),
    maximum: actual(Math.max(0, good - 1)),
  };
}
