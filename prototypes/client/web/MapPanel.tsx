import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { Board, terrainName, unitName, type Position } from "./Board";
import { fitTileSize, terrainLabel, unitLabel } from "./presentation";
import type { BattleState } from "./state";

export function MapPanel({
  battle,
  selected,
  select,
  empty,
  yourSlot,
}: {
  battle: BattleState | null;
  selected: Position | null;
  select: (position: Position) => void;
  empty: string;
  yourSlot: number | null;
}) {
  const [size, setSize] = useState(58);
  const [fit, setFit] = useState(true);
  const [coordinates, setCoordinates] = useState(false);
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
      </div>
      <p className="hint">
        {fit
          ? `Fits automatically on resize; tiles stay at least ${coordinates ? 44 : 36} px for legibility. Scroll if needed.`
          : "Manual tile size; enable Fit to map to resize automatically."}{" "}
        Property owners appear at the top; unit owners and internal health
        appear below. Your units have an underlined label.
      </p>
      <p id="empty" hidden={!!battle}>
        {empty}
      </p>
      <div id="map-scroll" ref={scroll}>
        <Board
          battle={battle}
          selected={selected}
          select={select}
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
