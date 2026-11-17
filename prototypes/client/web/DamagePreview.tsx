import type { BattleState, UnitState } from "./state";
import type { Position } from "./Board";
import { estimateAttackDamage } from "./damage_preview";
import "./DamagePreview.css";

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
