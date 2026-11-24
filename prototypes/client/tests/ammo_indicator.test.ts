import { describe, expect, it } from "vitest";
import {
  ammoInspectorValue,
  ammoStatus,
  ammoWarningLabel,
  ammoWarningVisible,
} from "../web/ammo_indicator";
import { validateState, type BattleState, type UnitState } from "../web/state";
import fixture from "./fixtures/state.json";

const snapshot = validateState(fixture);
const battle = snapshot.observation!.game_state.battle.value!;

const unit = (overrides: Partial<UnitState>): UnitState => ({
  reference: 1,
  army_slot: 1,
  unit_slot: 1,
  unit_type: 5,
  x: 0,
  y: 0,
  internal_health: 100,
  ammo: 9,
  fuel: 70,
  used_this_turn: false,
  embarked: false,
  capture_points: 0,
  cargo_references: [],
  submerged: false,
  ...overrides,
});

const fogged = (
  value: boolean | null,
  status: "available" | "unknown" = "available",
): BattleState => ({
  ...battle,
  fog_enabled: { status, value, reasons: [] },
});

describe("ammunition indicator", () => {
  it("ignores units the cartridge declares as having no ammunition", () => {
    expect(ammoStatus(unit({ unit_type: 1, ammo: 0 }))).toBeNull();
    expect(ammoStatus(unit({ unit_type: 7, ammo: 0 }))).toBeNull();
  });

  it("treats anything below half capacity as low", () => {
    expect(ammoStatus(unit({ ammo: 9 }))?.low).toBe(false);
    expect(ammoStatus(unit({ ammo: 5 }))?.low).toBe(false);
    expect(ammoStatus(unit({ ammo: 4 }))?.low).toBe(true);
    expect(ammoStatus(unit({ ammo: 0 }))?.low).toBe(true);
  });

  it("labels empty primary ammunition that still has a secondary weapon", () => {
    const tank = ammoStatus(unit({ ammo: 0 }))!;
    expect(tank.empty).toBe(true);
    expect(tank.secondaryOnly).toBe(true);
    expect(ammoWarningLabel(tank)).toBe(
      "no primary ammunition left, 0 of 9; unlimited secondary weapon only",
    );
    expect(
      ammoWarningLabel(ammoStatus(unit({ unit_type: 10, ammo: 0 }))!),
    ).toBe("out of ammunition, 0 of 9");
    expect(ammoWarningLabel(ammoStatus(unit({ ammo: 4 }))!)).toBe(
      "low ammo, 4 of 9",
    );
  });

  it("never reports ammunition a fog match has not exposed", () => {
    const fog = fogged(true);
    expect(ammoWarningVisible(unit({ army_slot: 2, ammo: 4 }), fog, 1)).toBe(
      false,
    );
    expect(ammoWarningVisible(unit({ army_slot: 1, ammo: 4 }), fog, 1)).toBe(
      true,
    );
    expect(
      ammoWarningVisible(
        unit({ army_slot: 2, ammo: 4 }),
        fogged(null, "unknown"),
        1,
      ),
    ).toBe(false);
    expect(
      ammoWarningVisible(
        unit({ army_slot: 1, ammo: 4 }),
        fogged(null, "unknown"),
        null,
      ),
    ).toBe(false);
    // Fog off means every unit on the board is exposed.
    expect(
      ammoWarningVisible(unit({ army_slot: 2, ammo: 4 }), battle, null),
    ).toBe(true);
  });

  it("does not flag embarked passengers carried off the board", () => {
    expect(
      ammoWarningVisible(unit({ ammo: 1, embarked: true }), battle, 1),
    ).toBe(false);
  });

  it("annotates the inspector value only when the warning is reportable", () => {
    expect(ammoInspectorValue(unit({ ammo: 9 }), battle, 1)).toBe("9/9");
    expect(ammoInspectorValue(unit({ ammo: 4 }), battle, 1)).toBe("4/9 · low");
    expect(ammoInspectorValue(unit({ ammo: 0 }), battle, 1)).toBe(
      "0/9 · primary ammunition gone, unlimited secondary weapon only",
    );
    expect(
      ammoInspectorValue(unit({ army_slot: 2, ammo: 4 }), fogged(true), 1),
    ).toBe("4/9");
  });
});
