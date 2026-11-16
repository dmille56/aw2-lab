import type { BattleState } from "./state";
type PlayerState = BattleState["players"][number];

type ObservedInteger = {
  status: string;
  value: number | null;
  reasons?: string[];
};

const verifiedStars: Record<number, { power: number; super?: number }> = {
  1: { power: 3, super: 6 }, // Andy
  2: { power: 3, super: 6 }, // Max
  3: { power: 3 }, // Olaf's Power threshold is runtime-observed.
  4: { power: 3, super: 8 }, // Sami
  9: { power: 4, super: 7 }, // Drake
};

const formatUnits = (value: number) =>
  `${new Intl.NumberFormat("en-US").format(value)} charge units`;

export function activePowerLabel(value: number): string {
  if (value === 0) return "Inactive";
  if (value === 1) return "Power active";
  if (value === 2) return "Super Power active";
  return `unknown (unrecognized flag ${value})`;
}

export function powerMeterLabel(value: ObservedInteger): string {
  if (value.status !== "available" || value.value === null)
    return `${value.status}${value.reasons?.length ? `: ${value.reasons.join("; ")}` : ""}`;
  if (value.value < 0)
    return `unknown (unvalidated negative value ${value.value})`;
  if (value.value === 0) return "0 charge units (empty)";
  return formatUnits(value.value);
}

export function nextPowerThresholdLabel(
  coId: number,
  useCounter: ObservedInteger,
): string {
  if (useCounter.status !== "available" || useCounter.value === null) {
    const status = `${useCounter.status}${useCounter.reasons?.length ? `: ${useCounter.reasons.join("; ")}` : ""}`;
    return `Unavailable (use count ${status})`;
  }
  const stars = verifiedStars[coId];
  if (!stars) return "Unavailable (CO thresholds are not verified)";

  // AW2 increments this counter before calculating the cost of the next use.
  const nextUse = useCounter.value + 1;
  if (!Number.isInteger(nextUse) || nextUse < 1 || nextUse > 10)
    return "Unavailable (next-use counter is outside the verified range)";

  const chargePerStar =
    nextUse >= 10 ? 18000 : (9000 * (100 + 20 * nextUse)) / 100;
  const power = formatUnits(stars.power * chargePerStar);
  const superPower = stars.super
    ? formatUnits(stars.super * chargePerStar)
    : "unavailable (CO star count is not verified)";
  return `Power ${power} · Super ${superPower} (next use; reference only)`;
}

/** Readiness uses the current counter; the debit uses the incremented counter. */
export function powerReadiness(
  player: Pick<
    PlayerState,
    "co_id" | "active_power" | "power_meter" | "power_use_counter"
  >,
  kind: "normal" | "super",
): "ready" | "not_ready" | "unknown" {
  if (player.active_power !== 0) return "not_ready";
  const meter = player.power_meter;
  if (meter.status !== "available" || meter.value === null || meter.value < 0)
    return "unknown";
  if (meter.value === 0) return "not_ready";
  const counter = player.power_use_counter;
  if (counter.status !== "available" || counter.value === null)
    return "unknown";
  if (
    !Number.isInteger(counter.value) ||
    counter.value < 0 ||
    counter.value > 9
  )
    return "not_ready";
  const stars =
    kind === "normal"
      ? verifiedStars[player.co_id]?.power
      : verifiedStars[player.co_id]?.super;
  if (!stars) return "unknown";
  const threshold = stars * ((9000 * (100 + 20 * counter.value)) / 100);
  return meter.value >= threshold ? "ready" : "not_ready";
}

/** Only verified complete CO thresholds get a segmented visual meter. */
export function powerCharge(
  player: Pick<PlayerState, "co_id" | "power_meter" | "power_use_counter">,
) {
  const stars = verifiedStars[player.co_id];
  const count = player.power_use_counter;
  const meter = player.power_meter;
  if (
    !stars?.super ||
    count.status !== "available" ||
    count.value === null ||
    !Number.isInteger(count.value) ||
    count.value < 0 ||
    count.value > 9 ||
    meter.status !== "available" ||
    meter.value === null ||
    meter.value < 0
  )
    return null;
  const perStar = (9000 * (100 + 20 * count.value)) / 100;
  return {
    normalStars: stars.power,
    superStars: stars.super,
    perStar,
    maximum: perStar * stars.super,
    value: meter.value,
  };
}
