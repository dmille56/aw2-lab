import { useEffect, useMemo, useState } from "react";
import type { components } from "./generated/api";
import type { MatchIdentity, ViewState } from "./session";
import {
  parseCoordinate,
  parsePath,
  supportedProductionProperties,
  type GameplayAction,
} from "./command_input";
import type { StateResponse } from "./state";
import { unitName } from "./Board";

type Capabilities = components["schemas"]["CapabilitiesResponse"];
type Unit = components["schemas"]["UnitState"];
type ActionKind =
  | "move_wait"
  | "move_attack"
  | "move_capture"
  | "purchase"
  | "end_turn"
  | "surrender";

const actionLabels: Record<ActionKind, string> = {
  move_wait: "Move then wait",
  move_attack: "Move then attack",
  move_capture: "Move then capture",
  purchase: "Purchase unit",
  end_turn: "End turn",
  surrender: "Surrender",
};
const noProductionTypes: string[] = [];

export function CommandPanel({
  snapshot,
  identity,
  capabilities,
  view,
  onSubmit,
  onRetry,
  onCheckStatus,
}: {
  snapshot: StateResponse | null;
  identity: MatchIdentity | null;
  capabilities: Capabilities | null;
  view: ViewState;
  onSubmit: (action: GameplayAction, expectedRevision: number) => void;
  onRetry: () => void;
  onCheckStatus: () => void;
}) {
  const battleObservation = snapshot?.observation?.game_state.battle;
  const battle =
    battleObservation?.status === "available" ? battleObservation.value : null;
  const slot = identity?.role === "player" ? identity.player_slot : null;
  const slotNumber = slot === "slot_1" ? 1 : slot === "slot_2" ? 2 : null;
  const active =
    !!battle && !!slotNumber && battle.active_player_slot === slotNumber;
  const observationReady =
    !!snapshot &&
    snapshot.settled &&
    snapshot.observation?.action_readiness === "ready" &&
    snapshot.observation.identity_status === "available";
  const activeUnits = useMemo(
    () =>
      battle?.units.filter(
        (unit) =>
          unit.army_slot === slotNumber &&
          !unit.used_this_turn &&
          !unit.embarked,
      ) ?? [],
    [battle, slotNumber],
  );
  const [kind, setKind] = useState<ActionKind>("move_wait");
  const [unitId, setUnitId] = useState("");
  const [pathText, setPathText] = useState("");
  const [targetText, setTargetText] = useState("");
  const [propertyText, setPropertyText] = useState("");
  const [unitType, setUnitType] = useState("");
  const [formError, setFormError] = useState("");
  const [previewRevision, setPreviewRevision] = useState<number | null>(
    snapshot?.summary.revision ?? null,
  );
  const revision = snapshot?.summary.revision ?? null;
  useEffect(() => {
    if (previewRevision === null && revision !== null)
      setPreviewRevision(revision);
  }, [previewRevision, revision]);

  const identities = snapshot?.observation?.unit_identities ?? [];
  const unitsWithIdentity = activeUnits.flatMap((unit: Unit) => {
    const identityForUnit = identities.find(
      (entry) => entry.reference === unit.reference,
    );
    return identityForUnit ? [{ unit, id: identityForUnit.identity_id }] : [];
  });
  useEffect(() => {
    if (!unitsWithIdentity.some(({ id }) => id === unitId))
      setUnitId(unitsWithIdentity[0]?.id ?? "");
  }, [unitId, unitsWithIdentity]);

  const selectedUnit = unitsWithIdentity.find(({ id }) => id === unitId)?.unit;
  const propertyChoices = useMemo(
    () =>
      battle
        ? supportedProductionProperties(battle.properties, slotNumber ?? 0)
        : [],
    [battle, slotNumber],
  );
  const productionTypes =
    capabilities?.production_unit_types ?? noProductionTypes;
  useEffect(() => {
    if (
      propertyText &&
      !propertyChoices.some(({ x, y }) => `${x},${y}` === propertyText)
    )
      setPropertyText("");
    if (!propertyText && propertyChoices[0])
      setPropertyText(`${propertyChoices[0].x},${propertyChoices[0].y}`);
  }, [propertyChoices, propertyText]);
  useEffect(() => {
    if (unitType && !productionTypes.includes(unitType)) setUnitType("");
    if (!unitType && productionTypes[0]) setUnitType(productionTypes[0]);
  }, [productionTypes, unitType]);

  const actionFeature = capabilities?.actions.find(({ name }) => name === kind);
  const actionAvailable =
    !!actionFeature?.implemented && !!actionFeature.available;
  const command = view.command;
  const commandPending =
    !!command &&
    ["submitting", "uncertain", "queued", "running"].includes(command.phase);
  const stale =
    previewRevision !== null &&
    revision !== null &&
    previewRevision !== revision;
  let preview: GameplayAction | null = null;
  let validationError = "";
  try {
    if (kind === "end_turn") preview = { contract_version: 1, kind };
    else if (kind === "surrender") preview = { contract_version: 1, kind };
    else if (kind === "purchase") {
      const property = propertyChoices.find(
        ({ x, y }) => `${x},${y}` === propertyText,
      );
      if (!property || !unitType)
        throw new Error(
          "Select an owned production base and an available unit type.",
        );
      preview = {
        contract_version: 1,
        kind,
        property: { contract_version: 1, x: property.x, y: property.y },
        unit_type: unitType,
      };
    } else {
      if (!selectedUnit || !unitId)
        throw new Error("Select one of your ready, identified units.");
      const path = parsePath(
        pathText,
        { contract_version: 1, x: selectedUnit.x, y: selectedUnit.y },
        battle?.map.width ?? 0,
        battle?.map.height ?? 0,
      );
      if (kind === "move_attack") {
        preview = {
          contract_version: 1,
          kind,
          unit_id: unitId,
          path,
          target: parseCoordinate(
            targetText,
            battle?.map.width ?? 0,
            battle?.map.height ?? 0,
          ),
        };
      } else {
        preview = { contract_version: 1, kind, unit_id: unitId, path };
      }
    }
  } catch (error) {
    validationError = error instanceof Error ? error.message : String(error);
  }

  const canPlay =
    view.connected &&
    view.ready &&
    identity?.role === "player" &&
    !!slotNumber &&
    active &&
    observationReady;
  let unavailableReason = "";
  if (!view.connected)
    unavailableReason = "Connect to a live match to submit actions.";
  else if (!view.ready)
    unavailableReason = "The live match is still synchronizing.";
  else if (identity?.role !== "player" || !slotNumber)
    unavailableReason =
      "Gameplay commands require an authenticated player identity.";
  else if (!battle) unavailableReason = "Live battle state is unavailable.";
  else if (!active) unavailableReason = "It is not your player slot's turn.";
  else if (!observationReady)
    unavailableReason =
      "The current observation is not settled and action-ready.";
  else if (!actionFeature?.implemented)
    unavailableReason = `The server does not implement ${actionLabels[kind]}.`;
  else if (!actionFeature.available)
    unavailableReason =
      actionFeature.unavailable_reason ||
      `${actionLabels[kind]} is unavailable.`;

  const selectAction = (value: string) => {
    if (value in actionLabels) {
      setKind(value as ActionKind);
      setFormError("");
    }
  };

  return (
    <section className="card command-panel" aria-label="Gameplay actions">
      <h2>Gameplay actions</h2>
      <p className="hint">
        Actions are checked against the live match. Enter every movement tile in
        order as <code>x,y</code>, separated by spaces; the server remains
        authoritative about gameplay legality.
      </p>
      <form
        id="gameplay-command"
        onSubmit={(event) => {
          event.preventDefault();
          setFormError("");
          if (!preview || validationError) {
            setFormError(
              validationError || "Complete the action details first.",
            );
            return;
          }
          if (stale || previewRevision === null) {
            setFormError(
              "This action preview is stale. Rebase it to the current revision before submitting.",
            );
            return;
          }
          if (
            kind === "surrender" &&
            !window.confirm(
              "Surrender this match? This action cannot be undone.",
            )
          )
            return;
          onSubmit(preview, previewRevision);
        }}
      >
        <label htmlFor="action-kind">Action</label>
        <select
          id="action-kind"
          value={kind}
          onChange={(event) => selectAction(event.currentTarget.value)}
          disabled={commandPending}
        >
          {Object.entries(actionLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {kind !== "end_turn" && kind !== "surrender" && kind !== "purchase" && (
          <>
            <label htmlFor="action-unit">Ready unit</label>
            <select
              id="action-unit"
              value={unitId}
              onChange={(event) => setUnitId(event.currentTarget.value)}
              disabled={commandPending || !unitsWithIdentity.length}
            >
              {unitsWithIdentity.map(({ unit, id }) => (
                <option key={id} value={id}>
                  {unitName(unit)} · ({unit.x},{unit.y}) · ID {id}
                </option>
              ))}
            </select>
            <label htmlFor="action-path">Explicit movement path</label>
            <textarea
              id="action-path"
              rows={3}
              placeholder="4,3 4,4"
              value={pathText}
              onChange={(event) => setPathText(event.currentTarget.value)}
              disabled={commandPending || !selectedUnit}
            />
            {kind === "move_attack" && (
              <>
                <label htmlFor="action-target">
                  Attack target coordinate (x,y)
                </label>
                <input
                  id="action-target"
                  value={targetText}
                  onChange={(event) => setTargetText(event.currentTarget.value)}
                  placeholder="5,4"
                  disabled={commandPending}
                />
              </>
            )}
          </>
        )}
        {kind === "purchase" && (
          <>
            <label htmlFor="purchase-property">Owned production base</label>
            <select
              id="purchase-property"
              value={propertyText}
              onChange={(event) => setPropertyText(event.currentTarget.value)}
              disabled={commandPending || !propertyChoices.length}
            >
              {propertyChoices.map(({ x, y }) => (
                <option key={`${x},${y}`} value={`${x},${y}`}>
                  ({x},{y})
                </option>
              ))}
            </select>
            {!propertyChoices.length && (
              <p role="status">
                No owned production base is available in this observation.
              </p>
            )}
            <label htmlFor="purchase-unit-type">Production unit type</label>
            <select
              id="purchase-unit-type"
              value={unitType}
              onChange={(event) => setUnitType(event.currentTarget.value)}
              disabled={commandPending || !productionTypes.length}
            >
              {productionTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </>
        )}
        {preview && (
          <div className="command-preview" aria-label="Action preview">
            <strong>
              {actionLabels[kind]} · revision {previewRevision ?? "unknown"}
            </strong>
            <code>{JSON.stringify(preview)}</code>
          </div>
        )}
        {stale && (
          <div className="command-stale" role="status">
            This preview uses revision {previewRevision}; the live match is now
            at revision {revision}.
            <button
              type="button"
              onClick={() => {
                setPreviewRevision(revision);
                setFormError("");
              }}
            >
              Rebase preview to revision {revision}
            </button>
          </div>
        )}
        {(validationError || formError) && (
          <p className="command-error" role="alert">
            {formError || validationError}
          </p>
        )}
        {unavailableReason && (
          <p className="hint" role="status">
            {unavailableReason}
          </p>
        )}
        <button
          type="submit"
          id="submit-action"
          disabled={
            !canPlay ||
            !actionAvailable ||
            commandPending ||
            stale ||
            !!validationError ||
            !preview
          }
        >
          Submit {actionLabels[kind]}
        </button>
      </form>
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
