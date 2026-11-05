import { useEffect, useRef } from "react";
import type { ViewState } from "./session";
import type { GameplayAction } from "./command_input";
import { positionLabel, type GameplayModel, type ActionKind } from "./gameplay";
import { unitName } from "./Board";
import catalog from "./catalog.json";

const labels: Record<ActionKind, string> = {
  move_wait: "Wait",
  move_attack: "Attack",
  move_capture: "Capture",
  purchase: "Purchase unit",
  end_turn: "End turn",
  surrender: "Surrender",
};

export function CommandPanel({
  model,
  view,
  onSubmit,
  onRetry,
  onCheckStatus,
}: {
  model: GameplayModel;
  view: ViewState;
  onSubmit: (action: GameplayAction, revision: number) => void;
  onRetry: () => void;
  onCheckStatus: () => void;
}) {
  const { draft, dispatch, editable, selectedUnit, destination } = model;
  const command = view.command;
  const panel = useRef<HTMLElement>(null);
  const previousPhase = useRef(draft.phase);
  useEffect(() => {
    if (previousPhase.current === draft.phase) return;
    previousPhase.current = draft.phase;
    const current = document.activeElement;
    if (current !== document.body && !panel.current?.contains(current)) return;
    if (
      draft.phase !== "review" &&
      draft.phase !== "target" &&
      current !== document.body
    )
      return;
    const next =
      draft.phase === "review"
        ? "#submit-action"
        : draft.phase === "target"
          ? "#action-target"
          : "#draft-heading";
    panel.current?.querySelector<HTMLElement>(next)?.focus();
  }, [draft.phase]);
  const choose = (kind: ActionKind) => {
    if (editable) dispatch({ type: "choose", kind });
  };
  const profileByName = (name: string) =>
    Object.values(catalog.units).find((unit) => unit.name === name);
  const funds = model.battle?.players.find(
    (player) => player.slot === model.slot,
  )?.funds;
  return (
    <section
      ref={panel}
      className="card command-panel"
      aria-label="Gameplay actions"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !model.pending) model.cancel();
      }}
    >
      <h2 id="draft-heading" tabIndex={-1}>
        Gameplay actions
      </h2>
      {draft.phase === "select" && !draft.base && (
        <p className="hint">
          Select your ready unit or production base on the board.
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
        <label htmlFor="purchase-property">Owned production base</label>
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
          <option value="">Choose a production base</option>
          {model.productionBases.map((p) => (
            <option key={`${p.x},${p.y}`} value={`${p.x},${p.y}`}>
              {positionLabel(p)}
            </option>
          ))}
        </select>
        {!model.productionBases.length && (
          <p>
            No unoccupied owned production base is available in this
            observation.
          </p>
        )}
      </details>
      {draft.origin && selectedUnit && (
        <div className="route-editor">
          <h3>
            {unitName(selectedUnit)} · from {positionLabel(draft.origin)}
          </h3>
          <p aria-label="Selected unit HP">
            HP: {selectedUnit.internal_health}/100
          </p>
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
          {draft.phase === "route" || draft.phase === "unit" ? (
            <>
              {draft.phase === "unit" && (
                <button
                  type="button"
                  disabled={!editable}
                  onClick={() => {
                    dispatch({ type: "plan" });
                    document
                      .querySelector<HTMLButtonElement>(
                        `#board button[data-x="${draft.origin?.x}"][data-y="${draft.origin?.y}"]`,
                      )
                      ?.focus();
                  }}
                >
                  Plan movement
                </button>
              )}
              {draft.phase === "route" && (
                <>
                  <p>
                    Activate adjacent tiles to add steps or an earlier step to
                    shorten the route. Arrow keys inspect; Enter/Space adds a
                    step.
                  </p>
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
                  <div className="toolbar">
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
                    <button
                      type="button"
                      disabled={!editable}
                      onClick={model.cancel}
                    >
                      Cancel movement
                    </button>
                  </div>
                </>
              )}
              <div className="toolbar">
                <button
                  type="button"
                  disabled={
                    !editable ||
                    !model.movementReady ||
                    !model.available("move_wait")
                  }
                  onClick={() => choose("move_wait")}
                >
                  Wait here
                </button>
                <button
                  type="button"
                  disabled={
                    !editable ||
                    !model.movementReady ||
                    !model.available("move_attack") ||
                    !model.canAttack
                  }
                  onClick={() => choose("move_attack")}
                >
                  Choose attack target
                </button>
                <button
                  type="button"
                  disabled={
                    !editable ||
                    !model.movementReady ||
                    !model.available("move_capture") ||
                    !model.canCapture
                  }
                  onClick={() => choose("move_capture")}
                >
                  Capture here
                </button>
              </div>
              {!model.canAttack && (
                <p>
                  Attack requires an attacking unit; indirect units must remain
                  in place.
                </p>
              )}
              {!model.canCapture && (
                <p>
                  Capture requires Infantry or Mech ending on a capturable
                  property not owned by your slot.
                </p>
              )}
            </>
          ) : (
            <button
              type="button"
              disabled={!editable}
              onClick={() => dispatch({ type: "edit" })}
            >
              Edit route
            </button>
          )}
        </div>
      )}
      {draft.phase === "target" && (
        <>
          <label htmlFor="action-target">Observed enemy target</label>
          <select
            id="action-target"
            value=""
            disabled={!editable}
            onChange={(event) => {
              const target = model.targets.find(
                (p) => `${p.x},${p.y}` === event.currentTarget.value,
              );
              if (target) model.activate(target);
            }}
          >
            <option value="">Choose a target</option>
            {model.targets.map((unit) => (
              <option key={unit.reference} value={`${unit.x},${unit.y}`}>
                {unitName(unit)} · {positionLabel(unit)}
              </option>
            ))}
          </select>
          <p>
            Targets are observed enemies; weapon compatibility and attack range
            are checked by the server.
          </p>
        </>
      )}
      {draft.base && (
        <>
          <h3>Production base {positionLabel(draft.base)}</h3>
          <p>
            Observed funds: {funds ?? "Unavailable"}. Costs below are baseline
            reference values.
          </p>
          {model.occupiedBase && (
            <p role="status">
              This base is occupied. Move its unit before purchasing.
            </p>
          )}
          <label htmlFor="purchase-unit-type">Production unit type</label>
          <select
            id="purchase-unit-type"
            value={draft.unitType}
            disabled={
              !editable || model.occupiedBase || !model.available("purchase")
            }
            onChange={(event) =>
              dispatch({
                type: "purchase",
                unitType: event.currentTarget.value,
              })
            }
          >
            <option value="">Choose a unit to purchase</option>
            {view.capabilities?.production_unit_types.map((name) => (
              <option key={name} value={name}>
                {name} · baseline cost {profileByName(name)?.cost ?? "unknown"}
              </option>
            ))}
          </select>
        </>
      )}
      <div className="toolbar">
        <button
          type="button"
          disabled={!editable || !model.available("end_turn")}
          onClick={() => choose("end_turn")}
        >
          End turn
        </button>
        <button
          type="button"
          disabled={!editable || !model.available("surrender")}
          onClick={() => choose("surrender")}
        >
          Surrender
        </button>
        <button type="button" disabled={model.pending} onClick={model.reset}>
          Cancel action
        </button>
      </div>
      {draft.phase === "review" && draft.kind && (
        <div className="command-preview" aria-label="Action preview">
          <h3>Confirm {labels[draft.kind]}</h3>
          {draft.kind.startsWith("move_") && selectedUnit && (
            <p>
              {unitName(selectedUnit)} from{" "}
              {draft.origin && positionLabel(draft.origin)} to{" "}
              {destination && positionLabel(destination)}. Route:{" "}
              {draft.path.length
                ? draft.path.map(positionLabel).join(" → ")
                : "stay in place"}
              .{" "}
              {draft.target && `Attack target: ${positionLabel(draft.target)}.`}
            </p>
          )}
          {draft.kind === "purchase" && draft.base && (
            <p>
              Buy {draft.unitType} at base {positionLabel(draft.base)}. Baseline
              cost: {profileByName(draft.unitType)?.cost ?? "unknown"}.
            </p>
          )}
          {draft.kind === "end_turn" && (
            <p>
              End your turn with {model.units.length} ready units remaining?
            </p>
          )}
          {draft.kind === "surrender" && (
            <p>Surrender this match? This action cannot be undone.</p>
          )}
          <p>Committed revision {view.snapshot?.summary.revision}</p>
          <button
            id="submit-action"
            type="button"
            disabled={!model.action}
            onClick={() => {
              if (model.action && view.snapshot)
                onSubmit(model.action, view.snapshot.summary.revision);
            }}
          >
            Confirm {labels[draft.kind]}
          </button>
        </div>
      )}
      <p role="status" aria-live="polite">
        {draft.notice}
      </p>
      {view.capabilities?.actions
        .filter((feature) => !feature.implemented || !feature.available)
        .map((feature) => (
          <p key={feature.name} className="hint">
            {feature.name}:{" "}
            {feature.unavailable_reason || "Unavailable on this server."}
          </p>
        ))}
      {model.unavailable && (
        <p className="hint" role="status">
          {model.unavailable}
        </p>
      )}
      {command && (
        <div className="command-result" aria-live="polite">
          <h3>Command status: {command.phase}</h3>
          <p>
            Request {command.request.request_id} · expected revision{" "}
            {command.request.expected_revision}
          </p>
          {command.receipt && (
            <p>
              Accepted as {command.receipt.command_id} · accepted revision{" "}
              {command.receipt.accepted_revision}
            </p>
          )}
          {command.result?.resulting_revision !== null &&
            command.result?.resulting_revision !== undefined && (
              <p>Resulting revision {command.result.resulting_revision}</p>
            )}
          {command.result?.error && (
            <details>
              <summary>
                {command.result.error.code}: {command.result.error.message}
              </summary>
              <pre>{JSON.stringify(command.result.error.details, null, 2)}</pre>
            </details>
          )}
          {command.phase === "uncertain" && (
            <button type="button" onClick={onRetry} disabled={!view.connected}>
              Retry safely with the same request ID
            </button>
          )}
          {command.receipt && ["queued", "running"].includes(command.phase) && (
            <button
              type="button"
              onClick={onCheckStatus}
              disabled={!view.connected}
            >
              Check command status
            </button>
          )}
        </div>
      )}
    </section>
  );
}
