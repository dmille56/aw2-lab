import { useEffect, useRef, useState } from "react";
import type { CommandProgress, ViewState } from "./session";
import type { GameplayAction } from "./command_input";
import { positionLabel, type GameplayModel, type ActionKind } from "./gameplay";
import { unitName } from "./Board";
import catalog from "./catalog.json";

const labels: Record<ActionKind, string> = {
  move_wait: "Wait",
  attack: "Attack in place",
  move_attack: "Attack",
  move_capture: "Capture",
  load: "Load",
  unload: "Unload",
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
  const activityMatch = useRef(view.snapshot?.summary.match_id ?? null);
  const [activity, setActivity] = useState<CommandProgress[]>([]);
  useEffect(() => {
    const matchId = view.snapshot?.summary.match_id ?? null;
    if (activityMatch.current === matchId) return;
    activityMatch.current = matchId;
    setActivity([]);
  }, [view.snapshot?.summary.match_id]);
  useEffect(() => {
    if (!command) return;
    setActivity((previous) => {
      const existing = previous.findIndex(
        (item) => item.request.request_id === command.request.request_id,
      );
      const updated = [...previous];
      if (existing >= 0) updated[existing] = command;
      else updated.push(command);
      return updated.slice(-8);
    });
  }, [command]);
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
  const preview = (() => {
    if (!draft.kind) return "";
    if (draft.kind === "purchase")
      return `Buy ${draft.unitType} at ${draft.base ? positionLabel(draft.base) : "the selected facility"}. Baseline cost: ${profileByName(draft.unitType)?.cost ?? "unknown"}.`;
    if (draft.kind === "end_turn")
      return "End your turn and pass control to the other player.";
    if (draft.kind === "surrender") return "Surrender this match.";
    if (draft.kind === "load")
      return `Move ${selectedUnit ? unitName(selectedUnit) : "the selected unit"} into the friendly carrier at ${destination ? positionLabel(destination) : "the route destination"}.`;
    if (draft.kind === "unload")
      return `Move the carrier to ${destination ? positionLabel(destination) : "its current tile"} and unload the selected cargo.`;
    const from = draft.origin
      ? positionLabel(draft.origin)
      : "its current tile";
    const to = destination ? positionLabel(destination) : from;
    const movement =
      draft.path.length > 0
        ? `Move ${selectedUnit ? unitName(selectedUnit) : "the unit"} from ${from} to ${to} via ${draft.path.map(positionLabel).join(" → ")}`
        : `Keep ${selectedUnit ? unitName(selectedUnit) : "the unit"} at ${from} (stay in place)`;
    if (draft.kind === "attack")
      return `Keep ${selectedUnit ? unitName(selectedUnit) : "the unit"} at ${from} and attack at ${draft.target ? positionLabel(draft.target) : "the selected target"}.`;
    if (draft.kind === "move_attack")
      return `${movement}, then attack at ${draft.target ? positionLabel(draft.target) : "the selected target"}.`;
    if (draft.kind === "move_capture")
      return `${movement}, then capture the property.`;
    return `${movement}, then wait.`;
  })();
  const activityEntries = command
    ? [
        ...activity.filter(
          (item) => item.request.request_id !== command.request.request_id,
        ),
        command,
      ].slice(-8)
    : activity;
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
          Select your ready unit or production facility on the board.
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
                    draft.path.length > 0 ||
                    !model.available("attack") ||
                    !model.canAttack
                  }
                  onClick={() => choose("attack")}
                >
                  Attack without moving
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
                {model.loadTransport && (
                  <button
                    type="button"
                    disabled={
                      !editable || !model.canLoad || !model.available("load")
                    }
                    onClick={() => {
                      if (model.loadAction && view.snapshot)
                        onSubmit(
                          model.loadAction,
                          view.snapshot.summary.revision,
                        );
                    }}
                  >
                    Load into {unitName(model.loadTransport)}
                  </button>
                )}
                {!!model.selectedTransportCargo.length && (
                  <button
                    type="button"
                    disabled={!editable || !model.destination}
                    onClick={() => choose("unload")}
                  >
                    Plan cargo unload
                  </button>
                )}
              </div>
              {!model.loadTransport ||
              !model.canLoad ||
              !model.available("load") ? (
                <p className="hint">{model.loadUnavailableReason}</p>
              ) : null}
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
          <h3>Production facility {positionLabel(draft.base)}</h3>
          <p>
            Observed funds: {funds ?? "Unavailable"}. Costs below are baseline
            reference values.
          </p>
          {model.occupiedBase && (
            <p role="status">
              This base is occupied. Move its unit before purchasing.
            </p>
          )}
          <label htmlFor="purchase-unit-type">Unit type</label>
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
            {model.purchaseUnitTypes.map((name) => (
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
          <p className="preview-summary">{preview}</p>
          {draft.kind === "unload" && selectedUnit && (
            <>
              <p>
                Move {unitName(selectedUnit)} to{" "}
                {destination && positionLabel(destination)} and drop selected
                cargo on adjacent legal tiles. The server checks the final route
                and drop positions before execution.
              </p>
              <fieldset className="unload-drops">
                <legend>Choose cargo and drop tiles</legend>
                {model.unloadDropOptions.map(
                  ({ unit, id, destinations: dropTiles }) => (
                    <label key={id}>
                      Drop {unitName(unit)} ({unit.internal_health}/100 HP)
                      <select
                        aria-label={`Drop ${unitName(unit)} at`}
                        value={
                          draft.dropDestinations[id]
                            ? `${draft.dropDestinations[id].x},${draft.dropDestinations[id].y}`
                            : ""
                        }
                        disabled={!editable || !dropTiles.length}
                        onChange={(event) => {
                          const tile = dropTiles.find(
                            (point) =>
                              `${point.x},${point.y}` ===
                              event.currentTarget.value,
                          );
                          dispatch({
                            type: "drop_destination",
                            unitId: id,
                            point: tile ?? null,
                          });
                        }}
                      >
                        <option value="">Keep aboard</option>
                        {dropTiles.map((point) => (
                          <option
                            key={`${point.x},${point.y}`}
                            value={`${point.x},${point.y}`}
                          >
                            {positionLabel(point)}
                          </option>
                        ))}
                      </select>
                    </label>
                  ),
                )}
              </fieldset>
              {model.unloadError && (
                <p role="alert" className="hint">
                  {model.unloadError}
                </p>
              )}
              {!model.available("unload") && (
                <p role="status" className="hint">
                  {model.unloadUnavailableReason}
                </p>
              )}
              {model.canUnload && model.available("unload") && (
                <p className="hint">
                  Drop tiles are unique, unoccupied, adjacent to the carrier,
                  and legal for each cargo unit's movement class.
                </p>
              )}
            </>
          )}
          {draft.kind === "end_turn" && (
            <div className="turn-confirmation">
              {model.units.length ? (
                <>
                  <p>
                    End your turn with {model.units.length} ready unit
                    {model.units.length === 1 ? "" : "s"} unused?
                  </p>
                  <ul aria-label="Unused units" className="unused-unit-list">
                    {model.units.map(({ unit, id }) => (
                      <li key={id}>
                        {unitName(unit)} · {positionLabel(unit)}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p>No ready units remain unused.</p>
              )}
            </div>
          )}
          {draft.kind === "surrender" && (
            <p role="alert" className="surrender-warning">
              Surrender will immediately forfeit this match. This action cannot
              be undone.
            </p>
          )}
          <p>
            This preview uses committed revision{" "}
            {view.snapshot?.summary.revision}. If the match changes, review it
            again before submitting.
          </p>
          <button
            id="submit-action"
            type="button"
            disabled={!model.action}
            onClick={() => {
              if (model.action && view.snapshot)
                onSubmit(model.action, view.snapshot.summary.revision);
            }}
          >
            {draft.kind === "surrender"
              ? "Surrender match"
              : draft.kind === "end_turn"
                ? "Confirm end turn"
                : `Confirm ${labels[draft.kind]}`}
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
        <section className="command-activity" aria-label="Command activity">
          <h3>Command activity</h3>
          <div
            className="command-result"
            aria-live="polite"
            data-status={command.phase}
          >
            <p className="activity-action">
              {labels[command.request.action.kind]}
            </p>
            <h4>Command status: {command.phase}</h4>
            <p className="activity-message" role="status">
              {command.phase === "submitting"
                ? "Sending this action to the match."
                : command.phase === "uncertain"
                  ? "The server may have accepted this action. Check its status or retry safely with the same request."
                  : command.phase === "queued" || command.phase === "running"
                    ? "Accepted by the server; waiting for the emulator to finish."
                    : command.phase === "completed"
                      ? "Completed and committed to the match."
                      : command.phase === "rolled_back"
                        ? "The action was rolled back. Its movement and other changes were undone; the board refreshes to the restored game state."
                        : "The action did not complete. Review the result details."}
            </p>
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
              <details className="command-error-details">
                <summary>
                  {command.result.error.code}: {command.result.error.message}
                </summary>
                <pre>
                  {JSON.stringify(command.result.error.details, null, 2)}
                </pre>
              </details>
            )}
            {command.phase === "uncertain" && (
              <button
                type="button"
                onClick={onRetry}
                disabled={!view.connected}
              >
                Retry safely with the same request ID
              </button>
            )}
            {command.receipt &&
              ["queued", "running"].includes(command.phase) && (
                <button
                  type="button"
                  onClick={onCheckStatus}
                  disabled={!view.connected}
                >
                  Check command status
                </button>
              )}
          </div>
          {activityEntries.length > 1 && (
            <details className="command-history">
              <summary>Previous actions ({activityEntries.length - 1})</summary>
              <ol>
                {activityEntries
                  .filter(
                    (item) =>
                      item.request.request_id !== command.request.request_id,
                  )
                  .reverse()
                  .map((item) => (
                    <li key={item.request.request_id}>
                      <span className="activity-action">
                        {labels[item.request.action.kind]}
                      </span>
                      <strong>Command status: {item.phase}</strong>
                      <p>
                        Request {item.request.request_id} · expected revision{" "}
                        {item.request.expected_revision}
                      </p>
                      {item.receipt && (
                        <p>
                          Accepted as {item.receipt.command_id} · accepted
                          revision {item.receipt.accepted_revision}
                        </p>
                      )}
                      {item.result?.resulting_revision !== null &&
                        item.result?.resulting_revision !== undefined && (
                          <p>
                            Resulting revision {item.result.resulting_revision}
                          </p>
                        )}
                      {item.result?.error && (
                        <details className="command-error-details">
                          <summary>
                            {item.result.error.code}:{" "}
                            {item.result.error.message}
                          </summary>
                          <pre>
                            {JSON.stringify(item.result.error.details, null, 2)}
                          </pre>
                        </details>
                      )}
                    </li>
                  ))}
              </ol>
            </details>
          )}
        </section>
      )}
    </section>
  );
}
