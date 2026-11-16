import type { GameplayModel } from "./gameplay";
import { positionLabel } from "./gameplay";
import { unitName } from "./Board";
import { restoreBoardFocus } from "./ContextActions";

/** Selection aids and explicit routing; actions live in the destination menu. */
export function CommandPanel({ model }: { model: GameplayModel }) {
  const { draft, dispatch, editable, selectedUnit, destination } = model;
  return (
    <section
      className="card command-panel"
      aria-label="Gameplay actions"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !model.pending) {
          model.cancel();
          restoreBoardFocus(draft.origin);
        }
      }}
    >
      <h2 id="draft-heading" tabIndex={-1}>
        Gameplay actions
      </h2>
      <p role="status" aria-live="polite">
        {model.pending
          ? "Waiting for the current action. Inspection remains available."
          : draft.notice ||
            "Select your ready unit or an empty production facility on the board."}
      </p>
      {model.unavailable && <p className="hint">{model.unavailable}</p>}
      {selectedUnit && (
        <p aria-label="Selected unit HP">
          HP: {selectedUnit.internal_health}/100
        </p>
      )}
      <details className="selection-lists">
        <summary>Choose a unit or base from lists</summary>
        <label htmlFor="action-unit">Ready unit</label>
        <select
          id="action-unit"
          value={draft.unitId}
          disabled={!editable}
          onChange={(event) => model.selectUnit(event.currentTarget.value)}
        >
          <option value="">Choose a ready unit</option>
          {model.units.map(({ unit, id }) => (
            <option key={id} value={id}>
              {unitName(unit)} · {positionLabel(unit)}
            </option>
          ))}
        </select>
        <label htmlFor="purchase-property">Owned production facility</label>
        <select
          id="purchase-property"
          value={draft.base ? `${draft.base.x},${draft.base.y}` : ""}
          disabled={!editable}
          onChange={(event) => {
            const base = model.productionBases.find(
              (p) => `${p.x},${p.y}` === event.currentTarget.value,
            );
            if (base) model.selectBase(base);
          }}
        >
          <option value="">Choose a production facility</option>
          {model.productionBases.map((p) => (
            <option key={`${p.x},${p.y}`} value={`${p.x},${p.y}`}>
              {positionLabel(p)}
            </option>
          ))}
        </select>
        {!model.productionBases.length && (
          <p>
            No unoccupied owned production facility is available in this
            observation.
          </p>
        )}
      </details>

      {draft.origin &&
        selectedUnit &&
        draft.phase === "route" &&
        draft.routeMode === "manual" && (
          <div className="route-editor">
            <h3>
              {unitName(selectedUnit)} · from {positionLabel(draft.origin)}
            </h3>
            <p>
              Destination: {destination && positionLabel(destination)} ·{" "}
              {draft.path.length} steps
            </p>
            <p>
              {draft.path.length
                ? draft.path.map(positionLabel).join(" → ")
                : "Act in place (no movement)."}
            </p>
            {draft.phase === "route" && model.movement && (
              <>
                <p>
                  Movement cost: {model.movement.cost} /{" "}
                  {model.movement.allowance ?? "unknown"} · Fuel:{" "}
                  {selectedUnit.fuel}
                </p>
                {model.movement.error && (
                  <p role="alert">{model.movement.error}</p>
                )}
                {model.movement.endpointError && (
                  <p role="status" className="hint">
                    {model.movement.endpointError}
                  </p>
                )}
                {model.battle?.fog_enabled.value === true && (
                  <p className="hint">
                    Only observed blockers can be checked. An unseen enemy stops
                    movement before its tile; the server verifies the reached
                    position.
                  </p>
                )}
              </>
            )}
            <p>
              Activate adjacent tiles to add steps or an earlier step to shorten
              the route. Arrow keys inspect; Enter/Space adds a step.
            </p>
            {draft.routeMode === "manual" && (
              <details>
                <summary>Choose route steps from a list</summary>
                <label htmlFor="next-step">Next adjacent step</label>
                <select
                  id="next-step"
                  value=""
                  disabled={!editable}
                  onChange={(event) => {
                    const tile = model.battle?.map.tiles.find(
                      (p) => `${p.x},${p.y}` === event.currentTarget.value,
                    );
                    if (tile) model.activate(tile);
                  }}
                >
                  <option value="">Choose next step</option>
                  {model.battle?.map.tiles
                    .filter(
                      (p) =>
                        destination &&
                        Math.abs(p.x - destination.x) +
                          Math.abs(p.y - destination.y) ===
                          1,
                    )
                    .map((p) => (
                      <option key={`${p.x},${p.y}`} value={`${p.x},${p.y}`}>
                        {positionLabel(p)}
                      </option>
                    ))}
                </select>
              </details>
            )}
            <div className="toolbar">
              <button
                type="button"
                disabled={!editable || !!model.movement?.error}
                onClick={() => dispatch({ type: "open_menu" })}
              >
                Choose action
              </button>
              <button
                type="button"
                disabled={!editable || !draft.path.length}
                onClick={() => dispatch({ type: "undo" })}
              >
                Undo step
              </button>
              <button
                type="button"
                disabled={!editable || !draft.path.length}
                onClick={() => dispatch({ type: "clear" })}
              >
                Clear path
              </button>
              <button type="button" disabled={!editable} onClick={model.cancel}>
                Cancel movement
              </button>
            </div>
          </div>
        )}
      {draft.phase !== "select" && !model.pending && (
        <button
          type="button"
          onClick={() => {
            model.reset();
            restoreBoardFocus(draft.origin ?? draft.base);
          }}
        >
          Cancel action
        </button>
      )}
    </section>
  );
}
