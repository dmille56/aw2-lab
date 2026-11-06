import { Fragment, useRef, type ReactNode } from "react";
import { terrainLabel, unitLabel } from "./presentation";
import catalogData from "./catalog.json";
import type { BattleState, StateResponse, UnitState } from "./state";

interface Profile {
  name: string;
  movement: number;
  movement_type: string;
  minimum_range: number;
  maximum_range: number;
  fuel_capacity: number;
  ammo_capacity: number;
  cost: number;
}
const catalog: {
  terrain: Record<number, string>;
  units: Record<number, Profile>;
} = catalogData;
export const owner = (slot: number) => (slot ? `Player ${slot}` : "Neutral");
export const terrainName = (id: number) =>
  catalog.terrain[id] ?? `Terrain ${id}`;
export const unitName = (unit: UnitState) =>
  catalog.units[unit.unit_type]?.name ?? `Unit ${unit.unit_type}`;
export const observed = (
  value: { status: string; value?: unknown; reasons?: string[] } | undefined,
) =>
  value?.status === "available"
    ? String(value.value)
    : `${value?.status ?? "unavailable"}${value?.reasons?.length ? `: ${value.reasons.join("; ")}` : ""}`;
export function Details({ entries }: { entries: [string, ReactNode][] }) {
  return (
    <dl>
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <dt>{key}</dt>
          <dd>{value ?? "Unavailable"}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
export function UnitInspector({
  unit,
  snapshot,
}: {
  unit: UnitState;
  snapshot: StateResponse;
}) {
  const profile = catalog.units[unit.unit_type];
  const identity = snapshot.observation?.unit_identities.find(
    (id) => id.reference === unit.reference,
  );
  return (
    <>
      <h3>
        {unitName(unit)} · {owner(unit.army_slot)}
      </h3>
      <Details
        entries={[
          ["Health (internal)", `${unit.internal_health}/100`],
          ["Turn status", unit.used_this_turn ? "Used" : "Ready"],
          ["Fuel", `${unit.fuel}${profile ? `/${profile.fuel_capacity}` : ""}`],
          ["Ammo", `${unit.ammo}${profile ? `/${profile.ammo_capacity}` : ""}`],
          ["Capture points (observed)", unit.capture_points],
          ["Embarked", unit.embarked ? "Yes" : "No"],
          ["Unit identity", identity?.identity_id ?? "Unavailable"],
          ["Cargo references", unit.cargo_references.join(", ") || "None"],
        ]}
      />
      {profile && (
        <>
          <h3>Baseline rule information</h3>
          <Details
            entries={[
              ["Movement", `${profile.movement} · ${profile.movement_type}`],
              [
                "Weapon range",
                `${profile.minimum_range}–${profile.maximum_range}`,
              ],
              ["Cost", profile.cost],
            ]}
          />
          <p className="hint">Current CO effects may change baseline rules.</p>
        </>
      )}
    </>
  );
}
export interface Position {
  x: number;
  y: number;
}
export function Board({
  battle,
  selected,
  select,
  coordinates = false,
  yourSlot = null,
  activate,
  cancel,
  route = [],
  target = null,
  reachable = new Set<string>(),
  transit = new Set<string>(),
  attackable = new Set<string>(),
  threatened = new Set<string>(),
}: {
  battle: BattleState | null;
  selected: Position | null;
  select: (position: Position) => void;
  coordinates?: boolean;
  yourSlot?: number | null;
  activate?: (position: Position) => void;
  cancel?: () => void;
  route?: Position[];
  target?: Position | null;
  reachable?: Set<string>;
  transit?: Set<string>;
  attackable?: Set<string>;
  threatened?: Set<string>;
}) {
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const occupancy = new Map(
    battle?.units.filter((u) => !u.embarked).map((u) => [`${u.x},${u.y}`, u]),
  );
  return (
    <div
      id="board"
      role="group"
      aria-label="Map tiles; arrow keys move selection"
      style={{
        gridTemplateColumns: `repeat(${battle?.map.width ?? 1}, var(--cell))`,
      }}
    >
      {battle &&
        [...battle.map.tiles]
          .sort((a, b) => a.y - b.y || a.x - b.x)
          .map((tile) => {
            const unit = occupancy.get(`${tile.x},${tile.y}`);
            const match = selected?.x === tile.x && selected.y === tile.y;
            const step = route.findIndex(
              (p) => p.x === tile.x && p.y === tile.y,
            );
            const destination = step >= 0 && step === route.length - 1;
            const isTarget = target?.x === tile.x && target.y === tile.y;
            const tileKey = `${tile.x},${tile.y}`;
            const isReachable = reachable.has(tileKey);
            const isTransit = transit.has(tileKey);
            const isAttackable = attackable.has(tileKey);
            const isThreatened = threatened.has(tileKey);
            return (
              <button
                key={`${tile.x},${tile.y}`}
                ref={(button) => {
                  if (button)
                    buttons.current.set(`${tile.x},${tile.y}`, button);
                  else buttons.current.delete(`${tile.x},${tile.y}`);
                }}
                type="button"
                data-x={tile.x}
                data-y={tile.y}
                className={`tile terrain-${tile.terrain_class} owner-${unit?.army_slot ?? tile.owner_slot}${match ? " selected" : ""}${isReachable ? " reachable" : ""}${isTransit ? " allied-transit" : ""}${isAttackable ? " attackable" : ""}${isThreatened ? " threatened" : ""}`}
                data-route-step={step >= 0 ? step : undefined}
                data-destination={destination || undefined}
                data-target={isTarget || undefined}
                data-your-unit={!!unit && unit.army_slot === yourSlot}
                title={`${terrainName(tile.terrain_class)}${unit ? ` · ${unitName(unit)}` : ""}`}
                aria-pressed={match}
                aria-label={`${step >= 0 ? `Route step ${step}${destination ? ", destination" : ""}, ` : ""}${isTarget ? "Attack target, " : ""}${isReachable ? "Reachable movement tile, " : ""}${isTransit ? "Allied transit only, " : ""}${isAttackable ? "Potential attack range, " : ""}${isThreatened ? "Potentially threatened by observed enemies, " : ""}(${tile.x}, ${tile.y}) ${terrainName(tile.terrain_class)}, ${owner(tile.owner_slot)}${unit ? `, ${unitName(unit)}, ${owner(unit.army_slot)}, health ${unit.internal_health}, ${unit.used_this_turn ? "used" : "ready"}${unit.army_slot === yourSlot ? ", your unit" : ""}` : ""}`}
                onClick={() => (activate ?? select)(tile)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    cancel?.();
                    return;
                  }
                  const delta: Record<string, [number, number]> = {
                    ArrowLeft: [-1, 0],
                    ArrowRight: [1, 0],
                    ArrowUp: [0, -1],
                    ArrowDown: [0, 1],
                  };
                  const move = delta[event.key];
                  if (!move) return;
                  event.preventDefault();
                  const next = {
                    x: Math.max(
                      0,
                      Math.min(battle.map.width - 1, tile.x + move[0]),
                    ),
                    y: Math.max(
                      0,
                      Math.min(battle.map.height - 1, tile.y + move[1]),
                    ),
                  };
                  select(next);
                  const button = buttons.current.get(`${next.x},${next.y}`);
                  button?.focus();
                  button?.scrollIntoView({
                    block: "nearest",
                    inline: "nearest",
                  });
                }}
              >
                {(step >= 0 || isTarget) && (
                  <span className="route-marker" aria-hidden="true">
                    {isTarget ? "T" : step === 0 ? "S" : step}
                    {destination ? "·D" : ""}
                  </span>
                )}
                <span className="owner-tag">P{tile.owner_slot || "–"}</span>
                <span className="terrain-label" aria-hidden="true">
                  {terrainLabel(
                    tile.terrain_class,
                    terrainName(tile.terrain_class),
                  )}
                </span>
                {unit && (
                  <>
                    <span className="unit" aria-hidden="true">
                      {unitLabel(unit.unit_type, unitName(unit))}
                    </span>
                    <span className="unit-health" aria-hidden="true">
                      P{unit.army_slot}·{unit.internal_health}
                      {unit.used_this_turn ? "✓" : ""}
                    </span>
                  </>
                )}
                <span className="coords" hidden={!coordinates}>
                  {tile.x},{tile.y}
                </span>
              </button>
            );
          })}
    </div>
  );
}
