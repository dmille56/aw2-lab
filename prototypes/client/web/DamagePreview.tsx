import type { BattleState, UnitState } from "./state";
import type { Position } from "./Board";
import { estimateAttackDamage } from "./damage_preview";
import "./DamagePreview.css";
import { TerrainDefense } from "./TerrainDefense";
import catalog from "./catalog.json";

export function DamagePreview({
  battle,
  attacker,
  defender,
  path,
}: {
  battle: BattleState;
  attacker: UnitState;
  defender: UnitState;
  path: Position[];
}) {
  const estimate = estimateAttackDamage(battle, attacker, defender, path);
  return (
    <div
      id="attack-damage-preview"
      className="damage-preview"
      role="status"
      aria-live="polite"
    >
      <p>
        <strong>Defending tile defense:</strong>{" "}
        <TerrainDefense
          terrainClass={
            battle.map.tiles.find(
              (tile) => tile.x === defender.x && tile.y === defender.y,
            )?.terrain_class
          }
        />
      </p>
      <small>Base terrain rating, before unit and CO modifiers.</small>
      {(catalog.units as Record<number, { movement_type: string }>)[
        defender.unit_type
      ]?.movement_type === "AIR" && (
        <p>Air units receive no terrain defense.</p>
      )}
      {estimate.status === "available" ? (
        <>
          <strong className="damage-value">
            Estimated damage: {estimate.forecast}%
          </strong>
          <p>
            With luck: {estimate.minimum}–{estimate.maximum}% of maximum health.
          </p>
          <small>Luck and rounding may change actual damage.</small>
        </>
      ) : (
        <>
          <strong>Damage estimate unavailable</strong>
          <p>{estimate.reason}</p>
        </>
      )}
    </div>
  );
}
