import { useEffect, useReducer } from "react";
import type { ViewState } from "./session";
import type { Position } from "./Board";
import type { GameplayAction } from "./command_input";
import { supportedProductionProperties } from "./command_input";
import catalog from "./catalog.json";
import { unloadDropTiles, validateMovement } from "./movement";

export type ActionKind = GameplayAction["kind"];
export interface Draft {
  boundary: string;
  unitId: string;
  origin: Position | null;
  base: Position | null;
  path: Position[];
  target: Position | null;
  unitType: string;
  kind: ActionKind | null;
  phase: "select" | "unit" | "route" | "target" | "review";
  notice: string;
  dropDestinations: Record<string, Position>;
}
export const sameTile = (a: Position, b: Position) =>
  a.x === b.x && a.y === b.y;
export const positionLabel = (p: Position) => `(${p.x},${p.y})`;
const FOOT_CARRIER_CARGO = new Set([1, 2]);
const LANDER_GROUND_MOVEMENT = new Set(["FOOT", "MECH", "TREADS", "WHEELS"]);
export function transportCanCarry(
  transportType: number,
  cargoType: number,
): boolean {
  if (transportType === 7 || transportType === 20)
    return FOOT_CARRIER_CARGO.has(cargoType);
  if (transportType !== 23) return false;
  const profile = (catalog.units as Record<number, { movement_type: string }>)[
    cargoType
  ];
  return !!profile && LANDER_GROUND_MOVEMENT.has(profile.movement_type);
}
export const emptyDraft = (boundary: string, notice = ""): Draft => ({
  boundary,
  unitId: "",
  origin: null,
  base: null,
  path: [],
  target: null,
  unitType: "",
  kind: null,
  phase: "select",
  notice,
  dropDestinations: {},
});
export type DraftEvent =
  | { type: "reset"; boundary: string; notice: string }
  | { type: "unit"; boundary: string; unitId: string; origin: Position }
  | { type: "base"; boundary: string; base: Position }
  | { type: "step"; point: Position }
  | { type: "undo" | "clear" | "edit" | "plan" | "cancel_route" }
  | { type: "choose"; kind: ActionKind }
  | { type: "target"; point: Position }
  | { type: "drop_destination"; unitId: string; point: Position | null }
  | { type: "purchase"; unitType: string }
  | { type: "notice"; notice: string };

export function draftReducer(draft: Draft, event: DraftEvent): Draft {
  switch (event.type) {
    case "reset":
      return emptyDraft(event.boundary, event.notice);
    case "unit":
      return {
        ...emptyDraft(event.boundary),
        unitId: event.unitId,
        origin: event.origin,
        phase: "unit",
        notice:
          "Unit selected. Choose Plan movement, or choose an action in place.",
      };
    case "base":
      return {
        ...emptyDraft(event.boundary),
        base: event.base,
        notice: "Production facility selected. Choose a unit to purchase.",
      };
    case "notice":
      return { ...draft, notice: event.notice };
    case "step": {
      if (!draft.origin || draft.phase !== "route") return draft;
      const route = [draft.origin, ...draft.path];
      const index = route.findIndex((p) => sameTile(p, event.point));
      if (index >= 0)
        return {
          ...draft,
          path: draft.path.slice(0, index),
          dropDestinations: {},
          notice: `Route shortened to ${positionLabel(event.point)}.`,
        };
      const last = route[route.length - 1];
      if (
        Math.abs(last.x - event.point.x) + Math.abs(last.y - event.point.y) !==
        1
      )
        return {
          ...draft,
          notice: "Choose a tile adjacent to the end of the route.",
        };
      if (draft.path.length >= 4096)
        return { ...draft, notice: "A route may contain at most 4096 steps." };
      return {
        ...draft,
        path: [...draft.path, event.point],
        dropDestinations: {},
        notice: `Step ${draft.path.length + 1}: ${positionLabel(event.point)}.`,
      };
    }
    case "undo":
      return {
        ...draft,
        path: draft.path.slice(0, -1),
        dropDestinations: {},
        notice: "Last step removed.",
      };
    case "clear":
      return {
        ...draft,
        path: [],
        dropDestinations: {},
        notice: "Route cleared. The unit will act in place.",
      };
    case "cancel_route":
      return {
        ...emptyDraft(draft.boundary),
        unitId: draft.unitId,
        origin: draft.origin,
        phase: draft.origin ? "unit" : "select",
        notice: "Movement cancelled. Unit selected.",
      };
    case "plan":
    case "edit":
      return {
        ...draft,
        phase: "route",
        kind: null,
        target: null,
        dropDestinations: {},
        notice: "Movement planning. Activate adjacent tiles to build a route.",
      };
    case "choose":
      return {
        ...(event.kind === "end_turn" ||
        event.kind === "surrender" ||
        event.kind === "activate_normal_power" ||
        event.kind === "activate_super_power"
          ? emptyDraft(draft.boundary)
          : draft),
        kind: event.kind,
        target: null,
        phase:
          event.kind === "move_attack" || event.kind === "attack"
            ? "target"
            : "review",
        notice:
          event.kind === "move_attack" || event.kind === "attack"
            ? "Choose an observed enemy unit on the board or from the target list."
            : "Review the action, then confirm to send it.",
      };
    case "target":
      return {
        ...draft,
        target: event.point,
        phase: "review",
        notice: `Target ${positionLabel(event.point)} selected. Review and confirm the attack.`,
      };
    case "drop_destination": {
      const dropDestinations = { ...draft.dropDestinations };
      if (event.point) dropDestinations[event.unitId] = event.point;
      else delete dropDestinations[event.unitId];
      return { ...draft, dropDestinations };
    }
    case "purchase":
      return {
        ...draft,
        unitType: event.unitType,
        kind: "purchase",
        phase: "review",
        notice: "Review the purchase, then confirm to send it.",
      };
  }
}

export function useGameplay(view: ViewState, inspect: (p: Position) => void) {
  const snapshot = view.snapshot;
  const observation = snapshot?.observation;
  const battle =
    observation?.game_state.battle.status === "available"
      ? observation.game_state.battle.value
      : null;
  const slot =
    view.identity?.role === "player"
      ? view.identity.player_slot === "slot_1"
        ? 1
        : 2
      : null;
  const boundary = `${view.connected}:${snapshot?.summary.match_id}:${snapshot?.summary.revision}:${slot}`;
  const [draft, dispatch] = useReducer(draftReducer, boundary, emptyDraft);
  useEffect(() => {
    if (draft.boundary === boundary) return;
    dispatch({
      type: "reset",
      boundary,
      notice: "Match state changed. Start a new action from the current board.",
    });
  }, [boundary, draft.boundary]);
  const pending =
    !!view.command &&
    ["submitting", "uncertain", "queued", "running"].includes(
      view.command.phase,
    );
  const ready =
    view.connected &&
    view.ready &&
    !!slot &&
    !!battle &&
    battle.active_player_slot === slot &&
    snapshot?.summary.lifecycle === "playable" &&
    !!snapshot?.settled &&
    observation?.action_readiness === "ready" &&
    observation.identity_status === "available";
  const editable = ready && !pending && draft.boundary === boundary;
  const units = (battle?.units ?? []).flatMap((unit) => {
    const identity = observation?.unit_identities.find(
      (item) => item.reference === unit.reference,
    );
    return unit.army_slot === slot &&
      !unit.used_this_turn &&
      !unit.embarked &&
      identity
      ? [{ unit, id: identity.identity_id }]
      : [];
  });
  const bases = supportedProductionProperties(
    battle?.properties ?? [],
    slot ?? 0,
    view.capabilities?.production_facilities ?? [],
  );
  const productionBases = bases.filter(
    (base) =>
      !battle?.units.some((unit) => !unit.embarked && sameTile(unit, base)),
  );
  const selectedBase = productionBases.find((base) =>
    sameTile(base, draft.base ?? { x: -1, y: -1 }),
  );
  const purchaseUnitTypes =
    view.capabilities?.production_facilities?.find(
      (facility) => facility.terrain_class === selectedBase?.terrain_class,
    )?.unit_types ?? [];
  const targets = (battle?.units ?? []).filter(
    (unit) => unit.army_slot !== slot && !unit.embarked,
  );
  const selectedUnit = units.find((item) => item.id === draft.unitId)?.unit;
  const profile = selectedUnit
    ? (
        catalog.units as Record<
          number,
          {
            name: string;
            minimum_range: number;
            maximum_range: number;
            cost: number;
          }
        >
      )[selectedUnit.unit_type]
    : undefined;
  const destination = draft.path.at(-1) ?? draft.origin;
  const movement =
    battle && selectedUnit
      ? validateMovement(battle, selectedUnit, draft.path)
      : null;
  const selectedTransportCargo =
    selectedUnit && [7, 20, 23].includes(selectedUnit.unit_type)
      ? selectedUnit.cargo_references.flatMap((reference) => {
          const unit = battle?.units.find(
            (candidate) =>
              candidate.reference === reference && candidate.embarked,
          );
          const id = observation?.unit_identities.find(
            (identity) => identity.reference === reference,
          )?.identity_id;
          return unit && id ? [{ unit, id }] : [];
        })
      : [];
  const unloadDropOptions = selectedTransportCargo.map(({ unit, id }) => ({
    unit,
    id,
    destinations:
      battle && destination && selectedUnit
        ? unloadDropTiles(battle, selectedUnit, unit, destination)
        : [],
  }));
  const transportAtDestination =
    battle && destination
      ? battle.units.find(
          (unit) =>
            [7, 20, 23].includes(unit.unit_type) &&
            !unit.embarked &&
            sameTile(unit, destination),
        )
      : undefined;
  const transportCompatible =
    !!selectedUnit &&
    !!transportAtDestination &&
    transportCanCarry(transportAtDestination.unit_type, selectedUnit.unit_type);
  const transportHasCapacity =
    !!transportAtDestination &&
    transportAtDestination.cargo_references.length <
      (transportAtDestination.unit_type === 23 ? 2 : 1);
  const loadTransport =
    transportAtDestination?.army_slot === slot &&
    transportCompatible &&
    transportHasCapacity
      ? transportAtDestination
      : undefined;
  const movementReady =
    (!draft.path.length || !movement?.error) &&
    (!movement?.endpointError || (!!loadTransport && draft.kind === "load"));
  const loadTransportId = observation?.unit_identities.find(
    (item) => item.reference === transportAtDestination?.reference,
  )?.identity_id;
  const feature = (kind: ActionKind) =>
    view.capabilities?.actions.find((item) => item.name === kind);
  const available = (kind: ActionKind) =>
    !!feature(kind)?.implemented && !!feature(kind)?.available;
  const canLoad = !!loadTransport && !!loadTransportId && !movement?.error;
  const selectedDrops = unloadDropOptions.flatMap(
    ({ unit, id, destinations }) => {
      const point = draft.dropDestinations[id];
      return point &&
        destinations.some((candidate) => sameTile(candidate, point))
        ? [{ unit, id, point }]
        : [];
    },
  );
  const duplicateDrop =
    new Set(selectedDrops.map(({ point }) => `${point.x},${point.y}`)).size !==
    selectedDrops.length;
  const unloadError =
    !selectedUnit || ![7, 20, 23].includes(selectedUnit.unit_type)
      ? "Select a ready transport with cargo to unload."
      : !selectedTransportCargo.length
        ? "This transport has no identified cargo to unload."
        : !selectedDrops.length
          ? "Choose at least one cargo unit and an adjacent legal drop tile."
          : duplicateDrop
            ? "Each cargo unit needs a different drop tile."
            : selectedDrops.length > (selectedUnit.unit_type === 23 ? 2 : 1)
              ? "This transport cannot unload more cargo than it carries."
              : movement?.error
                ? movement.error
                : movement?.endpointError
                  ? movement.endpointError
                  : "";
  const unloadFeature = feature("unload");
  const unloadUnavailableReason = !selectedTransportCargo.length
    ? "Select a ready carrier with identified cargo."
    : !destination
      ? "Choose the carrier's final tile before selecting drop tiles."
      : unloadDropOptions.every((item) => item.destinations.length === 0)
        ? "No adjacent empty tiles have verified legal terrain for this cargo."
        : !unloadFeature?.implemented || !unloadFeature.available
          ? (unloadFeature?.unavailable_reason ??
            "The connected server does not currently enable unloading.")
          : unloadError;
  const occupiedBase =
    !!draft.base &&
    !!battle?.units.some(
      (unit) => !unit.embarked && sameTile(unit, draft.base!),
    );
  const canAttack =
    !!profile &&
    profile.maximum_range > 0 &&
    !(profile.minimum_range > 1 && draft.path.length > 0);
  const canCapture =
    !!selectedUnit &&
    [1, 2].includes(selectedUnit.unit_type) &&
    !!destination &&
    !battle?.units.some(
      (unit) =>
        unit.reference !== selectedUnit.reference &&
        !unit.embarked &&
        sameTile(unit, destination),
    ) &&
    !!battle?.properties.some(
      (p) =>
        sameTile(p, destination) &&
        p.owner_slot !== slot &&
        [6, 8, 10, 11, 14, 20].includes(p.terrain_class),
    );
  const loadUnavailableReason = !transportAtDestination
    ? "End the route on a friendly carrier tile to load."
    : transportAtDestination.army_slot !== slot
      ? "Only a friendly transport can load this unit."
      : !transportCompatible
        ? "This carrier cannot carry the selected unit type."
        : !transportHasCapacity
          ? "This carrier has no free cargo space."
          : !loadTransportId
            ? "The carrier identity is unavailable in this observation."
            : movement?.error
              ? movement.error
              : !available("load")
                ? (feature("load")?.unavailable_reason ??
                  "The connected server does not currently enable loading.")
                : "";
  const reset = () =>
    dispatch({ type: "reset", boundary, notice: "Action cancelled." });
  const cancel = () => {
    if (pending) return;
    if (draft.origin && draft.phase !== "unit") {
      inspect(draft.origin);
      dispatch({ type: "cancel_route" });
    } else reset();
  };
  const selectUnit = (id: string) => {
    if (!editable) return;
    const item = units.find((item) => item.id === id);
    if (!item) return;
    inspect(item.unit);
    dispatch({
      type: "unit",
      boundary,
      unitId: id,
      origin: { x: item.unit.x, y: item.unit.y },
    });
  };
  const selectBase = (point: Position) => {
    if (!editable || !bases.some((p) => sameTile(p, point))) return;
    inspect(point);
    dispatch({ type: "base", boundary, base: point });
  };
  const inspectTile = (point: Position) => {
    inspect(point);
    if (
      !pending &&
      ((draft.base && !sameTile(draft.base, point)) ||
        (draft.phase === "unit" &&
          draft.origin &&
          !sameTile(draft.origin, point)))
    )
      dispatch({
        type: "reset",
        boundary,
        notice:
          "Selection cleared. Select a ready unit or production facility.",
      });
  };
  const activate = (point: Position) => {
    inspectTile(point);
    if (!editable || !battle?.map.tiles.some((tile) => sameTile(tile, point)))
      return;
    if (draft.phase === "route") {
      const route = draft.origin ? [draft.origin, ...draft.path] : [];
      const index = route.findIndex((tile) => sameTile(tile, point));
      const candidate =
        index >= 0 ? draft.path.slice(0, index) : [...draft.path, point];
      const report = selectedUnit
        ? validateMovement(battle, selectedUnit, candidate)
        : null;
      if (candidate.length && report?.error) {
        dispatch({ type: "notice", notice: report.error });
        return;
      }
      dispatch({ type: "step", point });
      if (report?.endpointError)
        dispatch({ type: "notice", notice: report.endpointError });
      return;
    }
    if (draft.phase === "target") {
      if (targets.some((unit) => sameTile(unit, point)))
        dispatch({ type: "target", point });
      else
        dispatch({
          type: "notice",
          notice: "Choose an observed enemy unit as the attack target.",
        });
      return;
    }
    const item = units.find((item) => sameTile(item.unit, point));
    if (item) selectUnit(item.id);
    else if (bases.some((p) => sameTile(p, point))) selectBase(point);
    else
      dispatch({
        type: "notice",
        notice: "Select one of your ready units or production facilities.",
      });
  };
  const coordinate = (p: Position) => ({
    contract_version: 1 as const,
    x: p.x,
    y: p.y,
  });
  const loadAction: GameplayAction | null =
    editable &&
    draft.phase === "route" &&
    selectedUnit &&
    loadTransport &&
    loadTransportId &&
    canLoad &&
    available("load")
      ? {
          contract_version: 1,
          kind: "load",
          unit_id: draft.unitId,
          transport_id: loadTransportId,
          path: draft.path.map(coordinate),
        }
      : null;
  let action: GameplayAction | null = null;
  if (
    editable &&
    draft.phase === "review" &&
    draft.kind &&
    available(draft.kind)
  ) {
    const kind = draft.kind;
    if (
      kind === "end_turn" ||
      kind === "surrender" ||
      kind === "activate_normal_power" ||
      kind === "activate_super_power"
    )
      action = { contract_version: 1, kind };
    else if (
      kind === "purchase" &&
      draft.base &&
      !occupiedBase &&
      purchaseUnitTypes.includes(draft.unitType)
    )
      action = {
        contract_version: 1,
        kind,
        property: coordinate(draft.base),
        unit_type: draft.unitType,
      };
    else if (
      selectedUnit &&
      movementReady &&
      kind === "load" &&
      loadTransport &&
      loadTransportId &&
      available("load")
    )
      action = {
        contract_version: 1,
        kind,
        unit_id: draft.unitId,
        transport_id: loadTransportId,
        path: draft.path.map(coordinate),
      };
    else if (
      selectedUnit &&
      movementReady &&
      kind === "unload" &&
      selectedTransportCargo.length > 0 &&
      selectedDrops.length > 0 &&
      !unloadError &&
      available("unload")
    )
      action = {
        contract_version: 1,
        kind,
        transport_id: draft.unitId,
        path: draft.path.map(coordinate),
        drops: selectedDrops.map(({ id, point }) => ({
          contract_version: 1,
          unit_id: id,
          destination: coordinate(point),
        })),
      };
    else if (
      selectedUnit &&
      movementReady &&
      (kind === "move_wait" || (kind === "move_capture" && canCapture))
    )
      action = {
        contract_version: 1,
        kind,
        unit_id: draft.unitId,
        path: draft.path.map(coordinate),
      };
    else if (
      selectedUnit &&
      movementReady &&
      kind === "attack" &&
      draft.path.length === 0 &&
      canAttack &&
      draft.target &&
      targets.some((u) => sameTile(u, draft.target!))
    )
      action = {
        contract_version: 1,
        kind,
        unit_id: draft.unitId,
        target: coordinate(draft.target),
      };
    else if (
      selectedUnit &&
      movementReady &&
      kind === "move_attack" &&
      canAttack &&
      draft.target &&
      targets.some((u) => sameTile(u, draft.target!))
    )
      action = {
        contract_version: 1,
        kind,
        unit_id: draft.unitId,
        path: draft.path.map(coordinate),
        target: coordinate(draft.target),
      };
  }
  const unavailable = !view.connected
    ? "Connect to a live match to submit actions."
    : !view.ready
      ? "The live match is still synchronizing."
      : !slot
        ? "Gameplay requires a player identity."
        : !battle
          ? "Live battle state is unavailable."
          : battle.active_player_slot !== slot
            ? "It is not your player slot's turn."
            : !ready
              ? "The match is not settled and action-ready."
              : pending
                ? "A command is pending. Editing is locked until its outcome is known."
                : "";
  return {
    draft,
    dispatch,
    boundary,
    pending,
    editable,
    ready,
    unavailable,
    units,
    bases,
    productionBases,
    purchaseUnitTypes,
    targets,
    selectedUnit,
    destination,
    occupiedBase,
    canAttack,
    canCapture,
    canLoad,
    loadAction,
    loadTransport: transportAtDestination,
    loadUnavailableReason,
    selectedTransportCargo,
    unloadDropOptions,
    unloadError,
    unloadUnavailableReason,
    canUnload: !unloadError,
    available,
    feature,
    action,
    reset,
    cancel,
    movement,
    movementReady,
    selectUnit,
    selectBase,
    activate,
    inspectTile,
    slot,
    battle,
  };
}
export type GameplayModel = ReturnType<typeof useGameplay>;
