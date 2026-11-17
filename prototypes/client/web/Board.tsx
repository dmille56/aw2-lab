import "./CargoBadge.css";
import { TerrainDefense } from "./TerrainDefense";
import "./UnitHealth.css";
import "./TargetHighlight.css";
import "./UnitSelection.css";
import "./RangeOverlay.css";
import { Fragment, useEffect, useRef, type ReactNode } from "react";
import { Sprite, type SpritePack } from "./sprites";
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
  const entries: [string, ReactNode][] = [
    ["HP", `${Math.ceil(unit.internal_health / 10)}/10`],
    ["Turn status", unit.used_this_turn ? "Used" : "Ready"],
    [
      "Tile defense",
      unit.embarked ? (
        "Unavailable while embarked"
      ) : (
        <TerrainDefense
          terrainClass={
            snapshot.observation?.game_state.battle.value?.map.tiles.find(
              (tile) => tile.x === unit.x && tile.y === unit.y,
            )?.terrain_class
          }
        />
      ),
    ],
    ["Fuel", `${unit.fuel}${profile ? `/${profile.fuel_capacity}` : ""}`],
    ["Ammo", `${unit.ammo}${profile ? `/${profile.ammo_capacity}` : ""}`],
  ];
  if (unit.cargo_references.length)
    entries.push(["Cargo", unit.cargo_references.length]);
  if (unit.capture_points > 0)
    entries.push(["Capture points", unit.capture_points]);
  if (unit.unit_type === 24)
    entries.push(["Submarine mode", unit.submerged ? "Submerged" : "Surfaced"]);
  return (
    <>
      <h3>
        {unitName(unit)} · {owner(unit.army_slot)}
      </h3>
      <Details entries={entries} />
      <details className="unit-details">
        <summary>Exact health, identity, and baseline rules</summary>
        <Details
          entries={[
            ["Health (internal)", `${unit.internal_health}/100`],
            ["Unit identity", identity?.identity_id ?? "Unavailable"],
            ["Embarked", unit.embarked ? "Yes" : "No"],
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
            <p className="hint">
              Current CO effects may change baseline rules.
            </p>
          </>
        )}
      </details>
    </>
  );
}
export interface UnitRangePreview {
  unit: UnitState;
  kind: "attack" | "movement";
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
  dropTargets = new Set<string>(),
  spritePack = null,
  dropSelections = {},
  actingUnitReference = null,
  enemyTargets = new Set<string>(),
  previewUnitRange,
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
  dropTargets?: Set<string>;
  spritePack?: SpritePack | null;
  dropSelections?: Record<string, string>;
  actingUnitReference?: number | null;
  enemyTargets?: Set<string>;
  previewUnitRange?: (preview: UnitRangePreview | null) => void;
}) {
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const heldPointer = useRef<{ id: number; button: number } | null>(null);
  useEffect(() => {
    const clear = () => {
      heldPointer.current = null;
      previewUnitRange?.(null);
    };
    const release = (event: PointerEvent) => {
      if (event.pointerId === heldPointer.current?.id) clear();
    };
    const changedButtons = (event: PointerEvent) => {
      const held = heldPointer.current;
      if (
        held &&
        event.pointerId === held.id &&
        !(event.buttons & (held.button === 1 ? 4 : 2))
      )
        clear();
    };
    const releaseMouse = (event: MouseEvent) => {
      if (event.button === heldPointer.current?.button) clear();
    };
    const visibility = () => {
      if (document.hidden) clear();
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("mouseup", releaseMouse);
    window.addEventListener("pointermove", changedButtons);
    window.addEventListener("pointercancel", release);
    window.addEventListener("blur", clear);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("mouseup", releaseMouse);
      window.removeEventListener("pointermove", changedButtons);
      window.removeEventListener("pointercancel", release);
      window.removeEventListener("blur", clear);
      document.removeEventListener("visibilitychange", visibility);
      clear();
    };
  }, [battle, previewUnitRange]);
  const occupancy = new Map(
    battle?.units.filter((u) => !u.embarked).map((u) => [`${u.x},${u.y}`, u]),
  );
  const tabStop = battle?.map.tiles.find(
    (tile) => tile.x === selected?.x && tile.y === selected?.y,
  ) ?? { x: 0, y: 0 };
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
            const terrainRegion =
              spritePack?.terrain[`${tile.terrain_class}:${tile.owner_slot}`];
            const unitRegion = unit
              ? spritePack?.units[`${unit.unit_type}:${unit.army_slot}`]
              : null;
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
            const isDropTarget = dropTargets.has(tileKey);
            const dropLabel = dropSelections[tileKey];
            const isActing = !!unit && unit.reference === actingUnitReference;
            const isEnemyTarget = !!unit && enemyTargets.has(tileKey);
            return (
              <button
                key={`${tile.x},${tile.y}`}
                ref={(button) => {
                  if (button)
                    buttons.current.set(`${tile.x},${tile.y}`, button);
                  else buttons.current.delete(`${tile.x},${tile.y}`);
                }}
                type="button"
                tabIndex={tile.x === tabStop.x && tile.y === tabStop.y ? 0 : -1}
                data-cargo-count={unit?.cargo_references.length || undefined}
                data-acting-unit={isActing || undefined}
                data-attackable-enemy={isEnemyTarget || undefined}
                data-drop-selected={dropLabel || undefined}
                data-x={tile.x}
                data-y={tile.y}
                className={`tile${terrainRegion ? " sprite-tile" : ""}${unit?.used_this_turn ? " used-unit" : ""} terrain-${tile.terrain_class} owner-${unit?.army_slot ?? tile.owner_slot}${match ? " selected" : ""}${isReachable ? " reachable" : ""}${isTransit ? " allied-transit" : ""}${isAttackable ? " attackable" : ""}${isThreatened ? " threatened" : ""}${isDropTarget ? " unload-drop-target" : ""}`}
                data-route-step={step >= 0 ? step : undefined}
                data-destination={destination || undefined}
                data-target={isTarget || undefined}
                data-drop-target={isDropTarget || undefined}
                data-your-unit={!!unit && unit.army_slot === yourSlot}
                title={`${terrainName(tile.terrain_class)}${unit ? ` · ${unitName(unit)}` : ""}`}
                aria-pressed={match}
                aria-label={`${isEnemyTarget ? "Attackable enemy, " : ""}${isActing ? "Selected acting unit, " : ""}${dropLabel ? `Cargo drop ${dropLabel}, ` : ""}${step >= 0 ? `Route step ${step}${destination ? ", destination" : ""}, ` : ""}${isTarget ? "Attack target, " : ""}${isReachable ? "Reachable movement tile, " : ""}${isTransit ? "Allied transit only, " : ""}${isAttackable ? "Potential attack range, " : ""}${isThreatened ? "Potentially threatened by observed enemies, " : ""}${isDropTarget ? "Valid unload drop tile, " : ""}(${tile.x}, ${tile.y}) ${terrainName(tile.terrain_class)}, ${owner(tile.owner_slot)}${unit ? `, ${unitName(unit)}, ${owner(unit.army_slot)}, health ${unit.internal_health}, ${unit.used_this_turn ? "used" : "ready"}${unit.army_slot === yourSlot ? ", your unit" : ""}${unit.cargo_references.length ? `, loaded transport, ${unit.cargo_references.length} passenger${unit.cargo_references.length === 1 ? "" : "s"} aboard` : ""}` : ""}`}
                onClick={() => (activate ?? select)(tile)}
                onPointerDown={(event) => {
                  if (
                    ![1, 2].includes(event.button) ||
                    !unit ||
                    !previewUnitRange
                  )
                    return;
                  event.preventDefault();
                  // The first held range gesture wins until its own button is released.
                  if (heldPointer.current) return;
                  heldPointer.current = {
                    id: event.pointerId,
                    button: event.button,
                  };
                  event.currentTarget.setPointerCapture?.(event.pointerId);
                  previewUnitRange({
                    unit,
                    kind: event.button === 1 ? "movement" : "attack",
                  });
                }}
                onMouseDown={(event) => {
                  if (unit && previewUnitRange && [1, 2].includes(event.button))
                    event.preventDefault();
                }}
                onAuxClick={(event) => {
                  if (event.button === 1 && unit && previewUnitRange)
                    event.preventDefault();
                }}
                onLostPointerCapture={() => {
                  if (heldPointer.current !== null) {
                    heldPointer.current = null;
                    previewUnitRange?.(null);
                  }
                }}
                onContextMenu={(event) => {
                  if (unit && previewUnitRange) {
                    event.preventDefault();
                    return;
                  }
                  if (cancel) {
                    event.preventDefault();
                    cancel();
                  }
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    heldPointer.current = null;
                    previewUnitRange?.(null);
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
                {(step >= 0 || isTarget || dropLabel) && (
                  <span className="route-marker" aria-hidden="true">
                    {dropLabel || (isTarget ? "T" : step === 0 ? "S" : step)}
                    {destination ? "·D" : ""}
                  </span>
                )}
                {(isReachable ||
                  isTransit ||
                  isAttackable ||
                  isThreatened ||
                  isDropTarget) && (
                  <span
                    aria-hidden="true"
                    className={`range-overlay${isReachable ? " movement-range" : ""}${isTransit ? " transit-range" : ""}${isAttackable ? " firing-range" : ""}${isThreatened ? " threat-range" : ""}${isDropTarget ? " drop-range" : ""}`}
                  />
                )}
                {isEnemyTarget && (
                  <span className="enemy-target-marker" aria-hidden="true">
                    <span className="enemy-target-label">ATTACK</span>
                  </span>
                )}
                {isActing && (
                  <span className="acting-unit-marker" aria-hidden="true">
                    <span className="acting-unit-label">SELECTED</span>
                  </span>
                )}
                {!!unit?.cargo_references.length && (
                  <span className="cargo-badge" aria-hidden="true">
                    C{unit.cargo_references.length}
                  </span>
                )}
                {spritePack && terrainRegion && (
                  <Sprite
                    pack={spritePack}
                    region={terrainRegion}
                    className="sprite-terrain"
                  />
                )}
                <span
                  className="terrain-label"
                  aria-hidden="true"
                  hidden={!!terrainRegion}
                >
                  {terrainLabel(
                    tile.terrain_class,
                    terrainName(tile.terrain_class),
                  )}
                </span>
                {unit && (
                  <>
                    {spritePack && unitRegion ? (
                      <Sprite
                        pack={spritePack}
                        region={unitRegion}
                        className="sprite-unit"
                      />
                    ) : (
                      <span className="unit" aria-hidden="true">
                        {unitLabel(unit.unit_type, unitName(unit))}
                      </span>
                    )}
                    <span className="unit-health" aria-hidden="true">
                      <strong>{Math.ceil(unit.internal_health / 10)}</strong>
                      {unit.used_this_turn && (
                        <span className="used-mark">✓</span>
                      )}
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
