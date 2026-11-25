import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  Board,
  terrainName,
  unitName,
  type Position,
  type UnitRangePreview,
} from "./Board";
import { BoardTurn, type BoardTurnMode, type VersusOutcome } from "./BoardTurn";
import { fitTileSize, terrainLabel, unitLabel } from "./presentation";
import type { BattleState } from "./state";
import type { UnitState } from "./state";
import { useSpritePack } from "./sprites";
import { movementReach } from "./movement";
import {
  enemyThreatCoverage,
  potentialAttackDescription,
  selectedAttackCoverage,
} from "./combat_overlay";

export function MapPanel({
  battle,
  onBoardWidthChange,
  turnMode = "snapshot",
  finished = false,
  outcome,
  selected,
  select,
  empty,
  yourSlot,
  activate,
  cancel,
  cancelAttackTarget,
  route,
  target,
  selectedUnit = null,
  selectedUnitKey = null,
  plannedRoute = [],
  dropTargets = new Set<string>(),
  actionTargets,
  enemyTargets = new Set<string>(),
  dropSelections = {},
}: {
  battle: BattleState | null;
  onBoardWidthChange?: (width: number | null) => void;
  turnMode?: BoardTurnMode;
  finished?: boolean;
  outcome?: VersusOutcome;
  selected: Position | null;
  select: (position: Position) => void;
  empty: string;
  yourSlot: number | null;
  activate?: (position: Position) => void;
  cancel?: () => void;
  cancelAttackTarget?: () => void;
  route?: Position[];
  target?: Position | null;
  selectedUnit?: UnitState | null;
  selectedUnitKey?: string | null;
  plannedRoute?: Position[];
  dropTargets?: Set<string>;
  actionTargets?: Set<string>;
  enemyTargets?: Set<string>;
  dropSelections?: Record<string, string>;
}) {
  const spritePack = useSpritePack(!!battle, { animateTerrain: true });
  const [heldRange, setHeldRange] = useState<{
    battle: BattleState;
    reference: number;
    kind: UnitRangePreview["kind"];
  } | null>(null);
  const previewUnitRange = useCallback(
    (preview: UnitRangePreview | null) => {
      setHeldRange(
        preview && battle
          ? { battle, reference: preview.unit.reference, kind: preview.kind }
          : null,
      );
    },
    [battle],
  );
  const heldUnit =
    heldRange?.battle === battle
      ? battle?.units.find((unit) => unit.reference === heldRange.reference)
      : null;
  const heldCoverage =
    battle && heldUnit && heldRange?.kind === "attack"
      ? selectedAttackCoverage(battle, heldUnit, [])
      : null;
  const heldMovement =
    battle && heldUnit && heldRange?.kind === "movement"
      ? movementReach(battle, heldUnit)
      : null;
  const [size, setSize] = useState(58);
  const [fit, setFit] = useState(true);
  const [coordinates, setCoordinates] = useState(false);
  const [showThreats, setShowThreats] = useState(false);
  const [attackRangeUnitKey, setAttackRangeUnitKey] = useState<string | null>(
    null,
  );
  useEffect(() => setAttackRangeUnitKey(null), [selectedUnitKey]);
  const scroll = useRef<HTMLDivElement>(null);
  const width = battle?.map.width;
  useLayoutEffect(() => {
    const node = scroll.current;
    if (!node || !width) {
      onBoardWidthChange?.(null);
      return;
    }
    const panel = node.closest<HTMLElement>(".map-panel");
    const workspace = node.closest<HTMLElement>(".workspace");
    const host = node.closest("main") ?? node;
    const measure = () => {
      const panelStyle = panel && getComputedStyle(panel);
      const inset = panelStyle
        ? parseFloat(panelStyle.paddingLeft) +
          parseFloat(panelStyle.paddingRight) +
          parseFloat(panelStyle.borderLeftWidth) +
          parseFloat(panelStyle.borderRightWidth)
        : 0;
      let available = node.clientWidth;
      if (workspace && host !== node) {
        const hostStyle = getComputedStyle(host);
        const sidebar =
          workspace.querySelector<HTMLElement>(".gameplay-sidebar");
        const beside =
          sidebar && getComputedStyle(sidebar).gridColumnStart === "2";
        // Fit against the full outer space, not the centered, shrink-wrapped
        // column. Otherwise a smaller board cannot grow again on resize.
        available =
          host.clientWidth -
          parseFloat(hostStyle.paddingLeft) -
          parseFloat(hostStyle.paddingRight) -
          inset -
          (beside
            ? sidebar.offsetWidth +
              parseFloat(getComputedStyle(workspace).columnGap)
            : 0);
      }
      if (available <= 0) return;
      const next = fit
        ? fitTileSize(available, width, coordinates ? 44 : 36)
        : size;
      if (fit) setSize(next);
      onBoardWidthChange?.(width * next + width - 1 + inset);
    };
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(host);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [fit, width, coordinates, size, onBoardWidthChange]);
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
        <BoardTurn
          battle={battle}
          yourSlot={yourSlot}
          mode={turnMode}
          finished={finished}
          outcome={outcome}
        />
        <button
          type="button"
          id="fit-map"
          aria-pressed={fit}
          onClick={() => setFit((value) => !value)}
        >
          Fit to width
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
      <p id="empty" hidden={!!battle}>
        {empty}
      </p>
      {!spritePack && battle && (
        <details className="sprite-setup">
          <summary>Map artwork: symbols</summary>
          <p>
            Extract a local sprite pack and start the prototype server with its
            sprite-pack directory to use game artwork. Symbols remain available
            for unmapped tiles and units.
          </p>
        </details>
      )}
      {cancelAttackTarget && (
        <div className="toolbar">
          <p role="status">Choose an ATTACK-marked enemy to preview damage.</p>
          <button
            type="button"
            onClick={cancelAttackTarget}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                cancelAttackTarget();
              }
            }}
          >
            Cancel target selection
          </button>
        </div>
      )}
      <div id="map-scroll" ref={scroll}>
        <Board
          battle={battle}
          spritePack={spritePack}
          selected={selected}
          select={select}
          activate={activate}
          cancel={cancel}
          route={route}
          target={target}
          dropTargets={dropTargets}
          dropSelections={dropSelections}
          reachable={heldMovement?.destinations ?? reach.destinations}
          transit={heldMovement?.alliedTransit ?? reach.alliedTransit}
          previewUnitRange={previewUnitRange}
          attackable={
            heldMovement
              ? new Set<string>()
              : (heldCoverage ??
                actionTargets ??
                (showAttackRange ? attacks : new Set<string>()))
          }
          threatened={heldMovement ? new Set<string>() : threats}
          enemyTargets={enemyTargets}
          actingUnitReference={selectedUnit?.reference ?? null}
          coordinates={coordinates}
          yourSlot={yourSlot}
        />
      </div>
      <p className="hint">
        {fit
          ? `Fits automatically on resize; tiles stay at least ${coordinates ? 44 : 36} px for legibility. Scroll if needed.`
          : "Manual tile size; enable Fit to width to resize automatically."}{" "}
        HP badges show health out of 10. Inspect a tile for unit and terrain
        ownership.
      </p>
      <p className="hint">
        Hold right-click on a unit for attack range or middle-click for movement
        range. Release to close. Escape or right-click an empty tile goes back.
      </p>
      {heldUnit && (
        <p className="hint" role="status">
          {heldMovement ? "Movement" : "Attack"} range preview:{" "}
          {unitName(heldUnit)} · Player {heldUnit.army_slot}. Release the{" "}
          {heldMovement ? "middle" : "right"} mouse button to close.
          {heldMovement &&
            (movementUnavailable
              ? ` Movement range unavailable because ${movementUnavailable}.`
              : heldMovement.destinations.size === 0
                ? " No reachable movement destinations in the observed rules."
                : "")}
          {heldCoverage?.size === 0 &&
            " No attack coverage is available for this unit."}
        </p>
      )}
      {!!enemyTargets.size && !cancelAttackTarget && (
        <p className="hint">
          Click an ATTACK-marked enemy to open its Attack menu.
        </p>
      )}
      {(!!route?.length || target) && (
        <p className="hint">
          Route markers: S = start, numbers = steps, D = destination, T = attack
          target. Outlines show the planned route; gameplay legality is checked
          by the server.
        </p>
      )}
      {(selectedUnit || heldUnit) && (
        <div className="range-key" aria-label="Range legend">
          {(selectedUnit || heldMovement) && (
            <span>
              <i aria-hidden="true" className="range-swatch movement-range" />
              Movement · translucent turquoise
            </span>
          )}
          {!!enemyTargets.size && <span>ATTACK · eligible enemy</span>}
          {!heldMovement && (showAttackRange || heldCoverage) && (
            <span>
              <i aria-hidden="true" className="range-swatch firing-range" />
              Attack · solid red border
            </span>
          )}
          {showThreats && !heldMovement && (
            <span>
              <i aria-hidden="true" className="range-swatch threat-range" />
              Enemy threats · dashed
            </span>
          )}
        </div>
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
      <details>
        <summary>Legend</summary>
        <p>
          HP badges show health out of 10, rounded up from internal health.
          Exact health remains in the inspector. ✓ marks used units. C1/C2 marks
          a loaded transport and its passenger count. ⚑ marks a property being
          captured. Full names and coordinates remain available to assistive
          technology and in the inspector. Terrain colors are illustrative.
          ATTACK markers identify eligible enemy units from the current or
          planned position, separately from general range coverage.
        </p>
        <p>
          Turquoise outlined tiles with a light translucent fill are reachable
          movement destinations; dashed turquoise tiles are allied transit. Red
          solid borders show potential attack range; turquoise inner borders
          retain movement reach where red ranges overlap. Red dashed tiles are
          in the enabled enemy threat estimate. These overlays describe observed
          potential coverage, not an action guarantee.
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
