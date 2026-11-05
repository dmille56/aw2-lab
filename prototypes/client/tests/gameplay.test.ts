import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { MatchSession, type ViewState } from "../web/session";
import { validateState } from "../web/state";
import { validateCapabilitiesResponse } from "../web/capabilities";
import stateFixture from "./fixtures/state.json";
import capabilityFixture from "./fixtures/capabilities.json";
import { useGameplay, draftReducer, emptyDraft } from "../web/gameplay";

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
    "move_attack",
    "move_capture",
    "purchase",
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
