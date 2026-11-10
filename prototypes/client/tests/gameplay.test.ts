import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { MatchSession, type ViewState } from "../web/session";
import { validateState, type StateResponse } from "../web/state";
import { validateCapabilitiesResponse } from "../web/capabilities";
import stateFixture from "./fixtures/state.json";
import capabilityFixture from "./fixtures/capabilities.json";
import {
  useGameplay,
  draftReducer,
  emptyDraft,
  transportCanCarry,
} from "../web/gameplay";
import { unloadDropTiles } from "../web/movement";

const selected = () =>
  draftReducer(
    draftReducer(emptyDraft("match:1"), {
      type: "unit",
      boundary: "match:1",
      unitId: "unit-1",
      origin: { x: 0, y: 0 },
    }),
    { type: "plan" },
  );

it("matches APC, Transport Copter, and Lander cargo rules", () => {
  for (const carrier of [7, 20]) {
    expect(transportCanCarry(carrier, 1)).toBe(true);
    expect(transportCanCarry(carrier, 2)).toBe(true);
    expect(transportCanCarry(carrier, 3)).toBe(false);
  }
  for (const cargo of [1, 2, 3, 5, 6, 7, 8, 10, 11, 14, 15])
    expect(transportCanCarry(23, cargo)).toBe(true);
  for (const cargo of [16, 17, 19, 20, 21, 22, 23, 24])
    expect(transportCanCarry(23, cargo)).toBe(false);
  expect(transportCanCarry(7, 23)).toBe(false);
});

describe("board action draft", () => {
  it("builds an adjacent route, rejects jumps, truncates and undoes steps", () => {
    let draft = selected();
    draft = draftReducer(draft, { type: "step", point: { x: 1, y: 0 } });
    const rejected = draftReducer(draft, {
      type: "step",
      point: { x: 2, y: 1 },
    });
    expect(rejected.path).toEqual(draft.path);
    expect(rejected.notice).toContain("adjacent");
    draft = draftReducer(draft, { type: "step", point: { x: 1, y: 1 } });
    draft = draftReducer(draft, { type: "step", point: { x: 1, y: 0 } });
    expect(draft.path).toEqual([{ x: 1, y: 0 }]);
    expect(draftReducer(draft, { type: "undo" }).path).toEqual([]);
    expect(draftReducer(draft, { type: "clear" }).path).toEqual([]);
    expect(
      draftReducer(draft, { type: "step", point: { x: 0, y: 0 } }).path,
    ).toEqual([]);
  });
  it("requires target selection before attack review and preserves the route when editing", () => {
    let draft = draftReducer(selected(), {
      type: "step",
      point: { x: 1, y: 0 },
    });
    draft = draftReducer(draft, { type: "choose", kind: "move_attack" });
    expect(draft.phase).toBe("target");
    draft = draftReducer(draft, { type: "target", point: { x: 1, y: 1 } });
    expect(draft.phase).toBe("review");
    draft = draftReducer(draft, { type: "edit" });
    expect(draft.target).toBeNull();
    expect(draft.path).toEqual([{ x: 1, y: 0 }]);
  });
  it("offers stationary attack target selection without adding a route", () => {
    let draft = draftReducer(selected(), { type: "choose", kind: "attack" });
    expect(draft.phase).toBe("target");
    expect(draft.path).toEqual([]);
    draft = draftReducer(draft, { type: "target", point: { x: 1, y: 1 } });
    expect(draft).toMatchObject({
      kind: "attack",
      phase: "review",
      path: [],
      target: { x: 1, y: 1 },
    });
  });
  it("cancels movement back to unit selection with no path or action", () => {
    let draft = draftReducer(selected(), {
      type: "step",
      point: { x: 1, y: 0 },
    });
    draft = draftReducer(draft, { type: "cancel_route" });
    expect(draft).toMatchObject({
      unitId: "unit-1",
      origin: { x: 0, y: 0 },
      phase: "unit",
      path: [],
      target: null,
      kind: null,
    });
  });
  it("discards unit, route, target and purchase state at a new boundary", () => {
    const draft = draftReducer(selected(), {
      type: "reset",
      boundary: "match:2",
      notice: "Match changed",
    });
    expect(draft).toEqual(emptyDraft("match:2", "Match changed"));
  });
});

it("builds a command only for the current ready boundary and locks uncertain submissions", () => {
  const capabilities = validateCapabilitiesResponse(capabilityFixture);
  capabilities.actions = [
    "move_wait",
    "attack",
    "move_attack",
    "move_capture",
    "join",
    "load",
    "purchase",
    "activate_normal_power",
    "end_turn",
    "surrender",
  ].map((name) => ({
    contract_version: 1,
    name,
    implemented: true,
    available: true,
    verification: "synthetic",
    unavailable_reason: null,
  }));
  const initial: ViewState = {
    ...new MatchSession().getSnapshot(),
    snapshot: validateState(stateFixture),
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: stateFixture.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
    capabilities,
  };
  const { result, rerender, unmount } = renderHook(
    ({ view }) => useGameplay(view, vi.fn()),
    { initialProps: { view: initial } },
  );
  act(() => result.current.selectUnit("1"));
  expect(result.current.draft.phase).toBe("unit");
  act(() => result.current.activate({ x: 1, y: 0 }));
  expect(result.current.draft.unitId).toBe("");
  act(() => result.current.selectUnit("1"));
  act(() => result.current.dispatch({ type: "plan" }));
  act(() => result.current.activate({ x: 1, y: 0 }));
  act(() => result.current.dispatch({ type: "choose", kind: "move_wait" }));
  expect(result.current.action).toEqual({
    contract_version: 1,
    kind: "move_wait",
    unit_id: "1",
    path: [{ contract_version: 1, x: 1, y: 0 }],
  });
  const request = {
    contract_version: 1 as const,
    request_id: "00000000-0000-4000-8000-000000000050",
    expected_revision: 1,
    action: result.current.action!,
  };
  rerender({
    view: {
      ...initial,
      command: { request, receipt: null, result: null, phase: "uncertain" },
    },
  });
  expect(result.current.editable).toBe(false);
  expect(result.current.action).toBeNull();
  act(() => result.current.activate({ x: 1, y: 1 }));
  expect(result.current.draft.path).toEqual([{ x: 1, y: 0 }]);
  const updated = structuredClone(stateFixture);
  updated.summary.revision = updated.observation.revision = 2;
  rerender({ view: { ...initial, snapshot: validateState(updated) } });
  expect(result.current.draft.unitId).toBe("");
  expect(result.current.draft.path).toEqual([]);
  expect(result.current.action).toBeNull();
  act(() => result.current.selectUnit("1"));
  rerender({ view: { ...initial, connected: false, identity: null } });
  expect(result.current.draft.unitId).toBe("");
  unmount();
});

it("submits Join only when the route ends on an unused same-type ally", () => {
  const state = structuredClone(stateFixture);
  state.observation.game_state.battle.value.units.push({
    ...state.observation.game_state.battle.value.units[0],
    reference: 2,
    unit_slot: 2,
    x: 1,
    y: 0,
  });
  state.observation.unit_identities.push({
    reference: 2,
    identity_id: "3",
    generation: 1,
  });
  const capabilities = validateCapabilitiesResponse(capabilityFixture);
  capabilities.actions = ["join"].map((name) => ({
    contract_version: 1,
    name,
    implemented: true,
    available: true,
    verification: "synthetic",
    unavailable_reason: null,
  }));
  const view: ViewState = {
    ...new MatchSession().getSnapshot(),
    snapshot: validateState(state),
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: state.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
    capabilities,
  };
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));
  act(() => result.current.selectUnit("1"));
  act(() => result.current.dispatch({ type: "plan" }));
  act(() => result.current.activate({ x: 1, y: 0 }));
  expect(result.current.joinReady).toBe(true);
  act(() => result.current.dispatch({ type: "choose", kind: "join" }));
  expect(result.current.action).toEqual({
    contract_version: 1,
    kind: "join",
    unit_id: "1",
    path: [{ contract_version: 1, x: 1, y: 0 }],
  });
  unmount();
});

it("builds normal Power independently of a selected unit", () => {
  const capabilities = validateCapabilitiesResponse(capabilityFixture);
  capabilities.actions = [
    {
      contract_version: 1,
      name: "activate_normal_power",
      implemented: true,
      available: true,
      verification: "synthetic",
      unavailable_reason: null,
    },
  ];
  const view: ViewState = {
    ...new MatchSession().getSnapshot(),
    snapshot: validateState(stateFixture),
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: stateFixture.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
    capabilities,
  };
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));

  act(() => result.current.selectUnit("1"));
  act(() =>
    result.current.dispatch({ type: "choose", kind: "activate_normal_power" }),
  );

  expect(result.current.draft).toMatchObject({
    kind: "activate_normal_power",
    phase: "review",
    unitId: "",
  });
  expect(result.current.action).toEqual({
    contract_version: 1,
    kind: "activate_normal_power",
  });
  unmount();
});

it("builds Super Power independently of a selected unit", () => {
  const capabilities = validateCapabilitiesResponse(capabilityFixture);
  capabilities.actions = ["activate_super_power"].map((name) => ({
    contract_version: 1,
    name,
    implemented: true,
    available: true,
    verification: "synthetic",
    unavailable_reason: null,
  }));
  const view: ViewState = {
    ...new MatchSession().getSnapshot(),
    snapshot: validateState(stateFixture),
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: stateFixture.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
    capabilities,
  };
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));

  act(() => result.current.selectUnit("1"));
  act(() =>
    result.current.dispatch({ type: "choose", kind: "activate_super_power" }),
  );

  expect(result.current.draft).toMatchObject({
    kind: "activate_super_power",
    phase: "review",
    unitId: "",
  });
  expect(result.current.action).toEqual({
    contract_version: 1,
    kind: "activate_super_power",
  });
  unmount();
});

it.each([
  ["dive", false],
  ["rise", true],
] as const)(
  "builds %s only for a Sub in the matching mode",
  (kind, submerged) => {
    const state = structuredClone(stateFixture) as StateResponse;
    if (!state.observation) throw new Error("fixture has no observation");
    const battle = state.observation.game_state.battle;
    if (battle.status !== "available" || !battle.value)
      throw new Error("fixture is not playable");
    battle.value.units[0] = {
      ...battle.value.units[0],
      unit_type: 24,
      fuel: 60,
      submerged,
    };
    const capabilities = validateCapabilitiesResponse(capabilityFixture);
    capabilities.actions = [kind].map((name) => ({
      contract_version: 1 as const,
      name,
      implemented: true,
      available: true,
      verification: "synthetic",
      unavailable_reason: null,
    }));
    const view: ViewState = {
      ...new MatchSession().getSnapshot(),
      snapshot: validateState(state),
      connected: true,
      ready: true,
      identity: {
        contract_version: 1,
        match_id: state.summary.match_id,
        role: "player",
        player_slot: "slot_1",
      },
      capabilities,
    };
    const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));
    act(() => result.current.selectUnit("1"));
    act(() => result.current.dispatch({ type: "plan" }));
    act(() => result.current.dispatch({ type: "choose", kind }));
    expect(result.current.action).toEqual({
      contract_version: 1,
      kind,
      unit_id: "1",
      path: [],
    });
    unmount();
  },
);

it("offers Load only on a compatible friendly carrier tile and builds its payload", () => {
  const capabilities = validateCapabilitiesResponse(capabilityFixture);
  capabilities.actions = ["load"].map((name) => ({
    contract_version: 1,
    name,
    implemented: true,
    available: true,
    verification: "synthetic",
    unavailable_reason: null,
  }));
  const state = structuredClone(stateFixture);
  const observation = state.observation;
  const battle = observation.game_state.battle;
  if (battle.status !== "available" || !battle.value)
    throw new Error("fixture is not playable");
  battle.value.units.push({
    ...battle.value.units[0],
    reference: 2,
    unit_slot: 2,
    unit_type: 7,
    x: 1,
    y: 0,
    used_this_turn: true,
  });
  observation.unit_identities.push({
    reference: 2,
    identity_id: "3",
    generation: 1,
  });
  const view: ViewState = {
    ...new MatchSession().getSnapshot(),
    snapshot: validateState(state),
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: state.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
    capabilities,
  };
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));
  act(() => result.current.selectUnit("1"));
  act(() => result.current.dispatch({ type: "plan" }));
  act(() => result.current.activate({ x: 1, y: 0 }));
  expect(result.current.canLoad).toBe(true);
  expect(result.current.loadAction).toEqual({
    contract_version: 1,
    kind: "load",
    unit_id: "1",
    transport_id: "3",
    path: [{ contract_version: 1, x: 1, y: 0 }],
  });
  expect(result.current.action).toBeNull();
  unmount();
});

function transportView(carrierType: number, cargoCount: number): ViewState {
  const capabilities = validateCapabilitiesResponse(capabilityFixture);
  capabilities.actions = ["unload"].map((name) => ({
    contract_version: 1,
    name,
    implemented: true,
    available: true,
    verification: "synthetic",
    unavailable_reason: null,
  }));
  const state = structuredClone(stateFixture) as StateResponse;
  if (!state.observation) throw new Error("fixture has no observation");
  const observation = state.observation;
  const battle = observation.game_state.battle;
  if (battle.status !== "available" || !battle.value)
    throw new Error("fixture is not playable");
  battle.value.units[0] = {
    ...battle.value.units[0],
    unit_type: carrierType,
    cargo_references: Array.from(
      { length: cargoCount },
      (_, index) => 3 + index,
    ),
  };
  for (let index = 0; index < cargoCount; index += 1) {
    const reference = 3 + index;
    battle.value.units.push({
      ...battle.value.units[0],
      reference,
      unit_slot: reference,
      unit_type: 1,
      x: 1,
      y: 0,
      embarked: true,
      used_this_turn: true,
      cargo_references: [],
    });
    observation.unit_identities.push({
      reference,
      identity_id: String(reference + 1),
      generation: 1,
    });
  }
  return {
    ...new MatchSession().getSnapshot(),
    snapshot: validateState(state),
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: state.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
    capabilities,
  };
}

it("plans a legal transport unload and includes the carrier route and cargo identity", () => {
  const view = transportView(7, 1);
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));
  act(() => result.current.selectUnit("1"));
  act(() => result.current.dispatch({ type: "plan" }));
  act(() => result.current.activate({ x: 1, y: 0 }));
  act(() => result.current.dispatch({ type: "choose", kind: "unload" }));
  const options = result.current.unloadDropOptions[0].destinations;
  expect(options).toContainEqual({ x: 0, y: 0 });
  expect(options).not.toContainEqual({ x: 1, y: 1 });
  act(() =>
    result.current.dispatch({
      type: "drop_destination",
      unitId: "4",
      point: { x: 0, y: 0 },
    }),
  );
  expect(result.current.action).toEqual({
    contract_version: 1,
    kind: "unload",
    transport_id: "1",
    path: [{ contract_version: 1, x: 1, y: 0 }],
    drops: [
      {
        contract_version: 1,
        unit_id: "4",
        destination: { contract_version: 1, x: 0, y: 0 },
      },
    ],
  });
  unmount();
});

it("plans distinct sequential drops for both cargo units in a Lander", () => {
  const view = transportView(23, 2);
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));
  act(() => result.current.selectUnit("1"));
  act(() => result.current.dispatch({ type: "choose", kind: "unload" }));
  act(() =>
    result.current.dispatch({
      type: "drop_destination",
      unitId: "4",
      point: { x: 1, y: 0 },
    }),
  );
  act(() =>
    result.current.dispatch({
      type: "drop_destination",
      unitId: "5",
      point: { x: 1, y: 0 },
    }),
  );
  expect(result.current.action).toBeNull();
  expect(result.current.unloadError).toContain("different drop tile");
  act(() =>
    result.current.dispatch({
      type: "drop_destination",
      unitId: "5",
      point: { x: 0, y: 1 },
    }),
  );
  expect(result.current.action).toMatchObject({
    kind: "unload",
    transport_id: "1",
    drops: [
      { unit_id: "4", destination: { x: 1, y: 0 } },
      { unit_id: "5", destination: { x: 0, y: 1 } },
    ],
  });
  unmount();
});

it("keeps unload submission disabled until the server advertises support", () => {
  const view = transportView(7, 1);
  if (!view.capabilities) throw new Error("fixture has no capabilities");
  view.capabilities.actions = [];
  const { result, unmount } = renderHook(() => useGameplay(view, vi.fn()));
  act(() => result.current.selectUnit("1"));
  act(() => result.current.dispatch({ type: "choose", kind: "unload" }));
  act(() =>
    result.current.dispatch({
      type: "drop_destination",
      unitId: "4",
      point: { x: 1, y: 0 },
    }),
  );
  expect(result.current.unloadError).toBe("");
  expect(result.current.action).toBeNull();
  expect(result.current.unloadUnavailableReason).toContain(
    "does not currently enable unloading",
  );
  unmount();
});

it("does not offer occupied or non-adjacent unload tiles", () => {
  const view = transportView(7, 1);
  const state = structuredClone(view.snapshot!);
  const battle = state.observation!.game_state.battle;
  if (battle.status !== "available" || !battle.value)
    throw new Error("fixture is not playable");
  expect(
    unloadDropTiles(
      battle.value,
      battle.value.units[0],
      battle.value.units[2],
      { x: 1, y: 0 },
    ),
  ).not.toContainEqual({ x: 1, y: 1 });
});
