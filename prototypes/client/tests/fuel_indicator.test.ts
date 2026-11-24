import { describe, expect, it } from "vitest";
import {
  fuelInspectorValue,
  fuelStatus,
  fuelWarningLabel,
  fuelWarningVisible,
} from "../web/fuel_indicator";
import { validateState, type UnitState } from "../web/state";
import fixture from "./fixtures/state.json";
const battle = validateState(fixture).observation!.game_state.battle.value!;
const unit = (overrides: Partial<UnitState> = {}): UnitState => ({
  ...battle.units[0],
  unit_type: 5,
  fuel: 70,
  army_slot: 1,
  embarked: false,
  ...overrides,
});
describe("fuel warnings", () => {
  it("flags fuel strictly below half capacity", () => {
    expect(fuelStatus(unit())?.low).toBe(false);
    expect(fuelStatus(unit({ fuel: 35 }))?.low).toBe(false);
    expect(fuelStatus(unit({ fuel: 34 }))?.low).toBe(true);
    expect(fuelStatus(unit({ unit_type: 999 }))).toBeNull();
  });
  it("distinguishes units at risk of destruction from ground units", () => {
    expect(fuelWarningLabel(fuelStatus(unit({ fuel: 0 }))!)).toContain(
      "cannot move",
    );
    expect(
      fuelWarningLabel(fuelStatus(unit({ unit_type: 16, fuel: 0 }))!),
    ).toContain("risk of destruction");
  });
  it("suppresses embarked units and other armies when fog is on or unknown", () => {
    const low = unit({ fuel: 1 });
    expect(fuelWarningVisible({ ...low, embarked: true }, battle, 1)).toBe(
      false,
    );
    for (const fog_enabled of [
      { status: "available" as const, value: true, reasons: [] },
      { status: "unknown" as const, value: null, reasons: [] },
    ]) {
      const fog = { ...battle, fog_enabled };
      expect(fuelWarningVisible(low, fog, 1)).toBe(true);
      expect(fuelWarningVisible({ ...low, army_slot: 2 }, fog, 1)).toBe(false);
      expect(fuelInspectorValue({ ...low, army_slot: 2 }, fog, 1)).toBe("1/70");
    }
    expect(fuelWarningVisible({ ...low, army_slot: 2 }, battle, 1)).toBe(true);
    expect(fuelInspectorValue(low, battle, 1)).toBe("1/70 · low");
  });
});
