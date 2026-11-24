import catalogData from "./catalog.json";
import type { BattleState, UnitState } from "./state";

const catalog: {
  units: Record<
    number,
    { fuel_capacity: number; destroyed_at_zero_fuel: boolean }
  >;
} = catalogData;

export interface FuelStatus {
  remaining: number;
  capacity: number;
  low: boolean;
  empty: boolean;
  destroyedAtZero: boolean;
}

export function fuelStatus(unit: UnitState): FuelStatus | null {
  const capacity = catalog.units[unit.unit_type]?.fuel_capacity;
  if (!capacity || capacity <= 0) return null;
  return {
    remaining: unit.fuel,
    capacity,
    low: unit.fuel * 2 < capacity,
    empty: unit.fuel <= 0,
    destroyedAtZero: catalog.units[unit.unit_type].destroyed_at_zero_fuel,
  };
}

export function fuelWarningVisible(
  unit: UnitState,
  battle: BattleState | null,
  viewerSlot: number | null,
): boolean {
  if (!battle || unit.embarked || !fuelStatus(unit)?.low) return false;
  if (battle.fog_enabled.status !== "available" || battle.fog_enabled.value) {
    return viewerSlot !== null && unit.army_slot === viewerSlot;
  }
  return true;
}

export function fuelWarningLabel(status: FuelStatus): string {
  if (status.empty)
    return status.destroyedAtZero
      ? `out of fuel, 0 of ${status.capacity}; unit is at risk of destruction`
      : `out of fuel, 0 of ${status.capacity}; unit cannot move`;
  return `low fuel, ${status.remaining} of ${status.capacity}`;
}

export function fuelInspectorValue(
  unit: UnitState,
  battle: BattleState | null,
  viewerSlot: number | null,
): string {
  const status = fuelStatus(unit);
  const count = `${unit.fuel}${status ? `/${status.capacity}` : ""}`;
  if (!status?.low || !fuelWarningVisible(unit, battle, viewerSlot))
    return count;
  if (!status.empty) return `${count} · low`;
  return `${count} · ${status.destroyedAtZero ? "out of fuel; risk of destruction" : "out of fuel; cannot move"}`;
}
