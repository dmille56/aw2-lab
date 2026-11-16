import { expect, it } from "vitest";
import {
  activePowerLabel,
  nextPowerThresholdLabel,
  powerMeterLabel,
  powerReadiness,
  powerCharge,
} from "../web/co_power";

const available = (value: number) => ({
  status: "available" as const,
  value,
  reasons: [],
});

it("labels inactive, Power, Super, and unrecognized active-power flags", () => {
  expect(activePowerLabel(0)).toBe("Inactive");
  expect(activePowerLabel(1)).toBe("Power active");
  expect(activePowerLabel(2)).toBe("Super Power active");
  expect(activePowerLabel(3)).toContain("unknown");
});

it("distinguishes an empty meter from unknown and unavailable readings", () => {
  expect(powerMeterLabel(available(0))).toBe("0 charge units (empty)");
  expect(powerMeterLabel(available(32400))).toBe("32,400 charge units");
  expect(
    powerMeterLabel({ status: "unknown", value: null, reasons: ["Not read"] }),
  ).toBe("unknown: Not read");
  expect(powerMeterLabel({ status: "unavailable", value: null })).toBe(
    "unavailable",
  );
  expect(powerMeterLabel(available(-1))).toContain("unknown");
});

it("shows verified next-use thresholds without implying action readiness", () => {
  expect(nextPowerThresholdLabel(1, available(0))).toBe(
    "Power 32,400 charge units · Super 64,800 charge units (next use; reference only)",
  );
  expect(nextPowerThresholdLabel(9, available(0))).toContain(
    "Power 43,200 charge units · Super 75,600 charge units",
  );
  expect(nextPowerThresholdLabel(3, available(0))).toContain(
    "Super unavailable (CO star count is not verified)",
  );
  expect(nextPowerThresholdLabel(18, available(0))).toContain("not verified");
  expect(nextPowerThresholdLabel(1, available(10))).toContain(
    "outside the verified range",
  );
  expect(
    nextPowerThresholdLabel(1, {
      status: "unknown",
      value: null,
      reasons: ["Counter not observed"],
    }),
  ).toContain("Counter not observed");
});

it("separates current readiness from the next activation debit", () => {
  const player = {
    co_id: 1,
    active_power: 0,
    power_meter: available(30000),
    power_use_counter: available(0),
  };
  expect(powerReadiness(player, "normal")).toBe("ready");
  expect(powerReadiness(player, "super")).toBe("not_ready");
  expect(powerReadiness({ ...player, active_power: 1 }, "normal")).toBe(
    "not_ready",
  );
  expect(powerReadiness({ ...player, co_id: 18 }, "normal")).toBe("unknown");
  expect(
    powerReadiness({ ...player, power_meter: available(0) }, "normal"),
  ).toBe("not_ready");
  expect(nextPowerThresholdLabel(1, available(9))).toContain(
    "Power 54,000 charge units · Super 108,000 charge units",
  );
});

it("uses current activation thresholds for segmented meters and preserves unknowns", () => {
  const player = {
    co_id: 1,
    power_meter: available(30000),
    power_use_counter: available(1),
  };
  expect(powerCharge(player)).toEqual({
    normalStars: 3,
    superStars: 6,
    perStar: 10800,
    maximum: 64800,
    value: 30000,
  });
  expect(powerCharge({ ...player, co_id: 18 })).toBeNull();
  expect(
    powerCharge({
      ...player,
      power_meter: { status: "unknown", value: null, reasons: [] },
    }),
  ).toBeNull();
});
