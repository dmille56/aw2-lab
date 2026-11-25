import type { PlayerStats } from "./state";

export function PlayerMatchStats({
  stats,
  includeFunds = false,
}: {
  stats?: PlayerStats;
  includeFunds?: boolean;
}) {
  const figures = [
    ["Units on board", stats?.unit_count, ""],
    ["Unit value", stats?.unit_value, " G"],
    ["Income properties", stats?.property_count, ""],
    ["Income per turn", stats?.income, " G"],
    ...(includeFunds ? [["Funds", stats?.funds, " G"]] : []),
  ] as const;
  return (
    <dl className="player-match-stats">
      {figures.map(([label, value, suffix]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            {value === null || value === undefined
              ? "Unavailable"
              : value.toLocaleString() + suffix}
          </dd>
        </div>
      ))}
    </dl>
  );
}
