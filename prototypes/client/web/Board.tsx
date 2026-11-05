import { Fragment, useRef, type ReactNode } from "react";
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
}: {
  battle: BattleState | null;
  selected: Position | null;
  select: (position: Position) => void;
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
                className={`tile terrain-${tile.terrain_class} owner-${unit?.army_slot ?? tile.owner_slot}${match ? " selected" : ""}`}
                aria-pressed={match}
                aria-label={`(${tile.x}, ${tile.y}) ${terrainName(tile.terrain_class)}, ${owner(tile.owner_slot)}${unit ? `, ${unitName(unit)}, ${owner(unit.army_slot)}, health ${unit.internal_health}, ${unit.used_this_turn ? "used" : "ready"}` : ""}`}
                onClick={() => select(tile)}
                onKeyDown={(event) => {
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
                <span className="owner-tag">P{tile.owner_slot || "–"}</span>
                <span>{terrainName(tile.terrain_class)}</span>
                {unit && (
                  <>
                    <span className="unit">{unitName(unit)}</span>
                    <span>
                      {unit.internal_health}/100
                      {unit.used_this_turn ? " ✓" : ""}
                    </span>
                  </>
                )}
                <span className="coords">
                  {tile.x},{tile.y}
                </span>
              </button>
            );
          })}
    </div>
  );
}
