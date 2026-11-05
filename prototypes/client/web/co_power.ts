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

  const chargePerStar = (9000 * (100 + 20 * nextUse)) / 100;
  const power = formatUnits(stars.power * chargePerStar);
  const superPower = stars.super
    ? formatUnits(stars.super * chargePerStar)
    : "unavailable (CO star count is not verified)";
  return `Power ${power} · Super ${superPower} (next use; reference only)`;
}
