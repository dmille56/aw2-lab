import catalogData from "./catalog.json";
import type { BattleState, UnitState } from "./state";

/*
  Advance Wars 2's Versus battle view has no per-unit ammunition marker on the
  board.  Isolated mGBA runs of Bean Island Versus (docs/AMMO-INDICATOR.md)
  compared the same tank at 9 and 0 ammunition across 120 frames: the only
  pixels that ever changed were the seven digits in the bottom-right status
  panel, never the unit's own tile.  There is therefore no cartridge artwork to
  extract, and this indicator is a clearly labelled symbolic badge rather than a
  copied icon.

  "Low" means strictly less than half of the unit's ammunition capacity, which
  matches Advance Wars: The Best Offense revision 63, where the flashing marker
  appeared below half ammunition instead of only at one round remaining.
*/

const catalog: {
  units: Record<number, { ammo_capacity: number; secondary_targets: number[] }>;
} = catalogData;

export interface AmmoStatus {
  remaining: number;
  capacity: number;
  low: boolean;
  empty: boolean;
  secondaryOnly: boolean;
}

export function ammoStatus(unit: UnitState): AmmoStatus | null {
  const profile = catalog.units[unit.unit_type];
  if (!profile || profile.ammo_capacity <= 0) return null;
  const remaining = unit.ammo;
  const capacity = profile.ammo_capacity;
  return {
    remaining,
    capacity,
    low: remaining * 2 < capacity,
    empty: remaining <= 0,
    secondaryOnly: remaining <= 0 && profile.secondary_targets.length > 0,
  };
}

export function ammoWarningVisible(
  unit: UnitState,
  battle: BattleState | null,
  viewerSlot: number | null,
): boolean {
  if (!battle || unit.embarked) return false;
  const status = ammoStatus(unit);
  if (!status?.low) return false;
  const fog = battle.fog_enabled;
  // Fog is a visibility claim, not an ammunition claim: while fog is on, or its
  // state is unverified, only report ammunition the viewer's own army controls.
  if (fog.status !== "available" || fog.value) {
    return viewerSlot !== null && unit.army_slot === viewerSlot;
  }
  return true;
}

export function ammoWarningLabel(status: AmmoStatus): string {
  if (status.empty) {
    return status.secondaryOnly
      ? `no primary ammunition left, 0 of ${status.capacity}; unlimited secondary weapon only`
      : `out of ammunition, 0 of ${status.capacity}`;
  }
  return `low ammo, ${status.remaining} of ${status.capacity}`;
}

/*
  The inspector already prints the ammunition number for every unit, so only the
  low or empty emphasis is fog-gated.
*/
export function ammoInspectorValue(
  unit: UnitState,
  battle: BattleState | null,
  viewerSlot: number | null,
): string {
  const status = ammoStatus(unit);
  const count = `${unit.ammo}${status ? `/${status.capacity}` : ""}`;
  if (!status?.low || !ammoWarningVisible(unit, battle, viewerSlot)) {
    return count;
  }
  if (!status.empty) return `${count} · low`;
  return status.secondaryOnly
    ? `${count} · primary ammunition gone, unlimited secondary weapon only`
    : `${count} · out of ammunition`;
}
