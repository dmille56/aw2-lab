import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { useState } from "react";
import { Board, type Position } from "../web/Board";
import { MatchControls, PurchaseMenu } from "../web/MatchControls";
import { ContextActions } from "../web/ContextActions";
import { joinCompatible, useGameplay } from "../web/gameplay";
import { MatchSession, type ViewState } from "../web/session";
import { validateState, type StateResponse } from "../web/state";
import { validateCapabilitiesResponse } from "../web/capabilities";
import type { GameplayAction } from "../web/command_input";
import fixture from "./fixtures/state.json";
import capabilitiesFixture from "./fixtures/capabilities.json";
afterEach(cleanup);
function viewWith(
  actions: string[],
  adjust: (state: StateResponse) => void,
): ViewState {
  const snapshot = validateState(structuredClone(fixture));
  adjust(snapshot);
  const capabilities = validateCapabilitiesResponse(capabilitiesFixture);
  capabilities.actions = ["move_wait", ...actions].map((name) => ({
    contract_version: 1,
    name,
    implemented: true,
    available: true,
    verification: "synthetic",
    unavailable_reason: null,
  }));
  return {
    ...new MatchSession().getSnapshot(),
    snapshot,
    capabilities,
    connected: true,
    ready: true,
    identity: {
      contract_version: 1,
      match_id: snapshot.summary.match_id,
      role: "player",
      player_slot: "slot_1",
    },
  };
}
function ally(state: StateResponse, unitType: number) {
  const battle = state.observation!.game_state.battle.value!;
  battle.units.push({
    ...battle.units[0],
    reference: 2,
    unit_slot: 2,
    unit_type: unitType,
    internal_health: 50,
    x: 1,
    y: 0,
    cargo_references: [],
  });
  state.observation!.unit_identities.push({
    reference: 2,
    identity_id: "3",
    generation: 1,
  });
}
function Harness({
  view,
  onSubmit,
}: {
  view: ViewState;
  onSubmit: (action: GameplayAction, revision: number) => void;
}) {
  const [selected, select] = useState<Position | null>(null);
  const model = useGameplay(view, select, {
    automaticRouting: true,
    onCommit: onSubmit,
  });
  return (
    <>
      <Board
        battle={model.battle}
        selected={selected}
        select={model.inspectTile}
        activate={model.activate}
        cancel={model.cancel}
        dropTargets={model.unloadTargets}
      />
      <ContextActions model={model} view={view} onSubmit={onSubmit} />
      <MatchControls model={model} view={view} onSubmit={onSubmit} />
      <PurchaseMenu model={model} view={view} onSubmit={onSubmit} />
    </>
  );
}
const tile = (x: number, y: number) =>
  screen.getByRole("button", { name: new RegExp(`\\(${x}, ${y}\\)`) });
async function selectInPlace() {
  await userEvent.click(tile(0, 0));
  await userEvent.click(tile(0, 0));
}
it.each(["supply", "dive", "rise"])(
  "commits %s directly from the unit menu",
  async (kind) => {
    const view = viewWith([kind], (state) => {
      const unit = state.observation!.game_state.battle.value!.units[0];
      unit.unit_type = kind === "supply" ? 7 : 24;
      unit.submerged = kind === "rise";
      if (kind === "supply") ally(state, 1);
    });
    const onSubmit = vi.fn();
    render(<Harness view={view} onSubmit={onSubmit} />);
    await selectInPlace();
    await userEvent.click(
      screen.getByRole("button", {
        name: kind[0].toUpperCase() + kind.slice(1),
      }),
    );
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
      { contract_version: 1, kind, unit_id: "1", path: [] },
      1,
    );
  },
);
it.each(["join", "load"])(
  "commits %s on an occupied compatible endpoint",
  async (kind) => {
    const view = viewWith([kind], (state) => {
      state.observation!.game_state.battle.value!.units[0].internal_health = 50;
      ally(state, kind === "join" ? 1 : 7);
    });
    const onSubmit = vi.fn();
    render(<Harness view={view} onSubmit={onSubmit} />);
    await userEvent.click(tile(0, 0));
    await userEvent.click(tile(1, 0));
    await userEvent.click(
      screen.getByRole("button", {
        name: kind === "join" ? "Join" : "Load",
      }),
    );
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
      {
        contract_version: 1,
        kind,
        unit_id: "1",
        ...(kind === "load" ? { transport_id: "3" } : {}),
        path: [{ contract_version: 1, x: 1, y: 0 }],
      },
      1,
    );
  },
);
it("commits a silo launch on board target selection", async () => {
  const view = viewWith(["silo_launch"], (state) => {
    state.observation!.game_state.battle.value!.map.tiles[0].terrain_class = 17;
  });
  const onSubmit = vi.fn();
  render(<Harness view={view} onSubmit={onSubmit} />);
  await selectInPlace();
  await userEvent.click(screen.getByRole("button", { name: "Launch missile" }));
  expect(onSubmit).not.toHaveBeenCalled();
  await userEvent.click(tile(1, 1));
  expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
    {
      contract_version: 1,
      kind: "silo_launch",
      unit_id: "1",
      path: [],
      target: { contract_version: 1, x: 1, y: 1 },
    },
    1,
  );
});
it("selects two distinct Lander drop tiles before one final unload command", async () => {
  const view = viewWith(["unload"], (state) => {
    const battle = state.observation!.game_state.battle.value!;
    battle.units[0].unit_type = 23;
    battle.units[0].cargo_references = [3, 4];
    for (const reference of [3, 4]) {
      battle.units.push({
        ...battle.units[0],
        reference,
        unit_slot: reference,
        unit_type: 1,
        embarked: true,
        used_this_turn: true,
        cargo_references: [],
      });
      state.observation!.unit_identities.push({
        reference,
        identity_id: String(reference + 1),
        generation: 1,
      });
    }
  });
  const onSubmit = vi.fn();
  render(<Harness view={view} onSubmit={onSubmit} />);
  await selectInPlace();
  await userEvent.click(screen.getByRole("button", { name: "Unload" }));
  for (const passenger of [1, 2]) {
    await userEvent.click(
      screen.getByRole("button", {
        name: `Passenger ${passenger}: Infantry`,
      }),
    );
    const target = passenger === 1 ? tile(1, 0) : tile(0, 1);
    await waitFor(() => expect(target).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Unload selected cargo" }),
      ).toHaveFocus(),
    );
  }
  expect(onSubmit).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "Unload selected cargo" }),
  );
  expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
    {
      contract_version: 1,
      kind: "unload",
      transport_id: "1",
      path: [],
      drops: [
        {
          contract_version: 1,
          unit_id: "4",
          destination: { contract_version: 1, x: 1, y: 0 },
        },
        {
          contract_version: 1,
          unit_id: "5",
          destination: { contract_version: 1, x: 0, y: 1 },
        },
      ],
    },
    1,
  );
});

it("confirms match controls, restores trigger focus, and gates observed power readiness", async () => {
  const view = viewWith(
    ["end_turn", "surrender", "activate_normal_power", "activate_super_power"],
    (state) => {
      const player = state.observation!.game_state.battle.value!.players[0];
      player.power_meter = { status: "available", value: 30000, reasons: [] };
      player.power_use_counter = { status: "available", value: 0, reasons: [] };
    },
  );
  const send = vi.fn();
  const user = userEvent.setup();
  render(<Harness view={view} onSubmit={send} />);
  expect(screen.getByRole("button", { name: "Super Power" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /^Power$/ }));
  expect(
    screen.getByRole("dialog", { name: "Confirm action" }),
  ).toHaveTextContent("normal Power");
  expect(send).not.toHaveBeenCalled();
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /^Power$/ })).toHaveFocus(),
  );
  await user.click(screen.getByRole("button", { name: "End turn" }));
  expect(screen.getByLabelText("Unused units")).toHaveTextContent("Infantry");
  await user.click(screen.getByRole("button", { name: "Confirm end turn" }));
  expect(send).toHaveBeenCalledWith(
    { contract_version: 1, kind: "end_turn" },
    1,
  );
});

it("Join requires a damaged destination, preserves equal damaged HP, and permits a full-health mover", () => {
  const state = validateState(structuredClone(fixture));
  ally(state, 1);
  const [source, , partner] = state.observation!.game_state.battle.value!.units;
  expect(joinCompatible(source, partner)).toBe(true);
  expect(joinCompatible(source, { ...partner, internal_health: 100 })).toBe(
    false,
  );
  expect(joinCompatible(source, { ...partner, internal_health: 91 })).toBe(
    false,
  );
  expect(joinCompatible({ ...source, internal_health: 50 }, partner)).toBe(
    true,
  );
  expect(joinCompatible(source, { ...partner, used_this_turn: true })).toBe(
    true,
  );
  expect(joinCompatible({ ...source, cargo_references: [2] }, partner)).toBe(
    false,
  );
});
