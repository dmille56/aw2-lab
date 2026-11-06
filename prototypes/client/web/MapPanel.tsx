import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Board, terrainName, unitName, type Position } from "./Board";
import { fitTileSize, terrainLabel, unitLabel } from "./presentation";
import type { BattleState } from "./state";
import type { UnitState } from "./state";
import { movementReach } from "./movement";
import {
  enemyThreatCoverage,
  potentialAttackDescription,
  selectedAttackCoverage,
} from "./combat_overlay";

export function MapPanel({
  battle,
  selected,
  select,
  empty,
  yourSlot,
  activate,
  cancel,
  route,
  target,
  selectedUnit = null,
  selectedUnitKey = null,
  plannedRoute = [],
}: {
  battle: BattleState | null;
  selected: Position | null;
  select: (position: Position) => void;
  empty: string;
  yourSlot: number | null;
  activate?: (position: Position) => void;
  cancel?: () => void;
  route?: Position[];
  target?: Position | null;
  selectedUnit?: UnitState | null;
  selectedUnitKey?: string | null;
  plannedRoute?: Position[];
}) {
  const [size, setSize] = useState(58);
  const [fit, setFit] = useState(true);
  const [coordinates, setCoordinates] = useState(false);
  const [showThreats, setShowThreats] = useState(false);
  const [attackRangeUnitKey, setAttackRangeUnitKey] = useState<string | null>(
    null,
  );
  useEffect(() => setAttackRangeUnitKey(null), [selectedUnitKey]);
  const scroll = useRef<HTMLDivElement>(null);
  const width = battle?.map.width,
    height = battle?.map.height;
  useLayoutEffect(() => {
    const node = scroll.current;
    if (!node || !fit || !width || !height) return;
    const measure = () => {
      if (node.clientWidth > 0)
        setSize(
          fitTileSize(
            node.clientWidth,
            Math.min(600, window.innerHeight * 0.65),
            width,
            height,
            coordinates ? 44 : 36,
          ),
        );
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [fit, width, height, coordinates]);
  const terrains = [
    ...new Set(battle?.map.tiles.map((tile) => tile.terrain_class)),
  ].sort((a, b) => a - b);
  const units = [
    ...new Map(battle?.units.map((unit) => [unit.unit_type, unit])).values(),
  ].sort((a, b) => a.unit_type - b.unit_type);
  const reach =
    battle && selectedUnit
      ? movementReach(battle, selectedUnit)
      : { destinations: new Set<string>(), alliedTransit: new Set<string>() };
  const attacks =
    battle && selectedUnit
      ? selectedAttackCoverage(battle, selectedUnit, plannedRoute)
      : new Set<string>();
  const showAttackRange =
    !!selectedUnit &&
    !!selectedUnitKey &&
    attackRangeUnitKey === selectedUnitKey;
  const threats =
    battle && showThreats && yourSlot
      ? enemyThreatCoverage(battle, yourSlot)
      : new Set<string>();
  const movementUnavailable = battle
    ? battle.fog_enabled.status !== "available" || battle.fog_enabled.value
      ? "fog is enabled or unknown and this snapshot has no per-unit visibility markers"
      : battle.weather.status !== "available" || battle.weather.value === null
        ? "observed weather is unavailable"
        : battle.co_effects_enabled.status !== "available"
          ? "the CO effects setting is unavailable"
          : ""
    : "battle data is unavailable";
  return (
    <section
      className="card map-panel"
      aria-label="Map"
      style={{ "--cell": `${size}px` } as CSSProperties}
    >
      <div className="toolbar">
        <h2>Board</h2>
        <button
          type="button"
          id="fit-map"
          aria-pressed={fit}
          onClick={() => setFit((value) => !value)}
        >
          Fit to map
        </button>
        <label className="checkbox-label">
          <input
            id="coordinates"
            type="checkbox"
            checked={coordinates}
            onChange={(event) => {
              setCoordinates(event.currentTarget.checked);
              if (event.currentTarget.checked)
                setSize((value) => Math.max(44, value));
            }}
          />
          Coordinates
        </label>
        <label>
          Tile size
          <input
            id="zoom"
            type="range"
            min={coordinates ? 44 : 36}
            max="90"
            value={size}
            onChange={(event) => {
              setFit(false);
              setSize(Number(event.currentTarget.value));
            }}
          />
        </label>
        <button
          type="button"
          id="attack-range"
          className="toggle-button"
          aria-pressed={showAttackRange}
          disabled={!selectedUnit || !selectedUnitKey || attacks.size === 0}
          onClick={() =>
            setAttackRangeUnitKey(showAttackRange ? null : selectedUnitKey)
          }
        >
          {showAttackRange ? "Hide attack range" : "Show attack range"}
        </button>
        <label className="checkbox-label">
          <input
            id="enemy-threats"
            type="checkbox"
            checked={showThreats}
            onChange={(event) => setShowThreats(event.currentTarget.checked)}
            disabled={!battle || !yourSlot}
          />
          Show enemy threat area
        </label>
      </div>
      <p className="hint">
        {fit
          ? `Fits automatically on resize; tiles stay at least ${coordinates ? 44 : 36} px for legibility. Scroll if needed.`
          : "Manual tile size; enable Fit to map to resize automatically."}{" "}
        Property owners appear at the top; unit owners and internal health
        appear below. Your units have an underlined label.
      </p>
      {(!!route?.length || target) && (
        <p className="hint">
          Route markers: S = start, numbers = steps, D = destination, T = attack
          target. Outlines show the planned route; gameplay legality is checked
          by the server.
        </p>
      )}
      {selectedUnit && battle && (
        <p className="hint" id="overlay-assumptions">
          {movementUnavailable
            ? `Movement reach unavailable because ${movementUnavailable}. `
            : "Movement and attack markings use observed rules. "}
          {showAttackRange
            ? potentialAttackDescription(selectedUnit)
            : "Movement range is shown for the selected unit. Show attack range to view its potential firing tiles."}
        </p>
      )}
      {showThreats && (
        <p className="hint" id="threat-assumptions">
          {battle?.fog_enabled.status !== "available" ||
          battle.fog_enabled.value
            ? "Threat coverage is unavailable while fog is enabled or its status is unknown; this observation has no per-unit visibility markers."
            : "Enemy threat area estimates coverage from observed enemy positions and reachable positions; future enemy choices are not shown."}
          {battle?.fog_enabled.status === "available" &&
            !battle.fog_enabled.value &&
            " Assumes each observed enemy could act on a future turn."}
        </p>
      )}
      <p id="empty" hidden={!!battle}>
        {empty}
      </p>
      <div id="map-scroll" ref={scroll}>
        <Board
          battle={battle}
          selected={selected}
          select={select}
          activate={activate}
          cancel={cancel}
          route={route}
          target={target}
          reachable={reach.destinations}
          transit={reach.alliedTransit}
          attackable={showAttackRange ? attacks : new Set<string>()}
          threatened={threats}
          coordinates={coordinates}
          yourSlot={yourSlot}
        />
      </div>
      <details>
        <summary>Legend</summary>
        <p>
          Unit health is internal health out of 100. ✓ marks used units. Full
          names and coordinates remain available to assistive technology and in
          the inspector. Terrain colors are illustrative.
        </p>
        <p>
          Blue dotted tiles are reachable movement destinations; striped tiles
          are allied units usable as route transit only. Orange tiles show
          potential attack range. Red hatched tiles are in the enabled enemy
          threat estimate. These overlays describe observed potential coverage,
          not an action guarantee.
        </p>
        <div id="legend">
          {terrains.map((id) => (
            <span key={`terrain-${id}`}>
              {terrainLabel(id, terrainName(id))} = {terrainName(id)}
            </span>
          ))}
          {units.map((unit) => (
            <span key={`unit-${unit.unit_type}`}>
              {unitLabel(unit.unit_type, unitName(unit))} = {unitName(unit)}
            </span>
          ))}
        </div>
      </details>
    </section>
  );
}
