import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { Board, UnitInspector } from "../web/Board";
import { MapPanel } from "../web/MapPanel";
import { Health } from "../web/Health";
import { App } from "../web/App";
import { CommandPanel } from "../web/CommandPanel";
import { validateCapabilitiesResponse } from "../web/capabilities";
import { useGameplay } from "../web/gameplay";
import { MatchSession, type ViewState } from "../web/session";
import { validateState } from "../web/state";
import { supportedProductionProperties } from "../web/command_input";
import fixture from "./fixtures/state.json";
import capabilityFixture from "./fixtures/capabilities.json";
const snapshot = validateState(fixture);
const battle = snapshot.observation?.game_state.battle.value;
if (!battle) throw new Error("Fixture has no battle");
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("React viewer", () => {
  it("offers Super Power as a separate, reviewed action", async () => {
    const capabilities = validateCapabilitiesResponse(capabilityFixture);
    capabilities.actions = [
      {
        contract_version: 1,
        name: "activate_super_power",
        implemented: true,
        available: true,
        verification: "synthetic",
        unavailable_reason: null,
      },
    ];
    const initial: ViewState = {
      ...new MatchSession().getSnapshot(),
      snapshot,
      connected: true,
      ready: true,
      identity: {
        contract_version: 1,
        match_id: snapshot.summary.match_id,
        role: "player",
        player_slot: "slot_1",
      },
      capabilities,
    };
    const onSubmit = vi.fn();
    function SuperPanel() {
      const model = useGameplay(initial, vi.fn());
      return (
        <CommandPanel
          model={model}
          view={initial}
          onSubmit={onSubmit}
          onRetry={vi.fn()}
          onCheckStatus={vi.fn()}
        />
      );
    }
    render(<SuperPanel />);

    await userEvent.click(
      screen.getByRole("button", { name: "Activate Super Power" }),
    );
    expect(
      screen.getByRole("heading", { name: "Confirm Activate Super Power" }),
    ).toBeVisible();
    expect(screen.getByText(/CO-specific meter cost/)).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm Activate Super Power" }),
    );
    expect(onSubmit).toHaveBeenCalledWith(
      { contract_version: 1, kind: "activate_super_power" },
      snapshot.summary.revision,
    );
  });

  it("offers normal Power and shows its pending, completed, and failed status", async () => {
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
    const initial: ViewState = {
      ...new MatchSession().getSnapshot(),
      snapshot,
      connected: true,
      ready: true,
      identity: {
        contract_version: 1,
        match_id: snapshot.summary.match_id,
        role: "player",
        player_slot: "slot_1",
      },
      capabilities,
    };
    const onSubmit = vi.fn();
    function PowerPanel({ view }: { view: ViewState }) {
      const model = useGameplay(view, vi.fn());
      return (
        <CommandPanel
          model={model}
          view={view}
          onSubmit={onSubmit}
          onRetry={vi.fn()}
          onCheckStatus={vi.fn()}
        />
      );
    }

    const rendered = render(<PowerPanel view={initial} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Activate normal Power" }),
    );
    expect(
      screen.getByRole("heading", { name: "Confirm Activate normal Power" }),
    ).toBeVisible();
    expect(
      screen.getByText(/server checks meter and activation state/),
    ).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm Activate normal Power" }),
    );
    const action = {
      contract_version: 1 as const,
      kind: "activate_normal_power" as const,
    };
    expect(onSubmit).toHaveBeenCalledWith(action, snapshot.summary.revision);

    const requestId = "00000000-0000-4000-8000-000000000051";
    const commandId = "00000000-0000-4000-8000-000000000052";
    const request = {
      contract_version: 1 as const,
      request_id: requestId,
      expected_revision: snapshot.summary.revision,
      action,
    };
    const receipt = {
      contract_version: 1 as const,
      command_id: commandId,
      request_id: requestId,
      match_id: snapshot.summary.match_id,
      accepted_revision: snapshot.summary.revision,
      status: "queued" as const,
    };
    const pending = {
      request,
      receipt,
      result: null,
      phase: "queued" as const,
    };
    rendered.rerender(<PowerPanel view={{ ...initial, command: pending }} />);
    expect(
      screen.getByRole("heading", { name: "Command status: queued" }),
    ).toBeVisible();
    expect(
      screen.getByText(/waiting for the emulator to finish/),
    ).toBeVisible();

    const completedResult = {
      contract_version: 1 as const,
      command_id: commandId,
      request_id: requestId,
      match_id: snapshot.summary.match_id,
      accepted_revision: snapshot.summary.revision,
      resulting_revision: snapshot.summary.revision + 1,
      checkpoint_id: null,
      error: null,
      status: "completed" as const,
    };
    rendered.rerender(
      <PowerPanel
        view={{
          ...initial,
          command: { ...pending, phase: "completed", result: completedResult },
        }}
      />,
    );
    expect(
      screen.getByText("Completed and committed to the match."),
    ).toBeVisible();

    rendered.rerender(
      <PowerPanel
        view={{ ...initial, command: { ...pending, phase: "rejected" } }}
      />,
    );
    expect(
      screen.getByText(
        "The action did not complete. Review the result details.",
      ),
    ).toBeVisible();
  });

  it("offers only owned production bases for purchase", () => {
    const properties = [
      { owner_slot: 1, terrain_class: 6, x: 0, y: 0 },
      { owner_slot: 1, terrain_class: 14, x: 1, y: 0 },
      { owner_slot: 2, terrain_class: 14, x: 0, y: 1 },
      { owner_slot: 1, terrain_class: 11, x: 2, y: 0 },
    ];
    const facilities = [
      {
        contract_version: 1 as const,
        terrain_class: 14,
        name: "base",
        unit_types: ["Infantry"],
      },
      {
        contract_version: 1 as const,
        terrain_class: 11,
        name: "seaport",
        unit_types: ["Battleship"],
      },
    ];
    expect(supportedProductionProperties(properties, 1, facilities)).toEqual([
      properties[1],
      properties[3],
    ]);
  });
  it("selects tiles with mouse and arrow keys while preserving focus", async () => {
    const select = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
    render(<Board battle={battle} selected={{ x: 0, y: 0 }} select={select} />);
    const first = screen.getAllByRole("button")[0];
    await userEvent.click(first);
    expect(select).toHaveBeenLastCalledWith(
      expect.objectContaining({ x: 0, y: 0 }),
    );
    await userEvent.keyboard("{ArrowRight}");
    expect(select).toHaveBeenLastCalledWith({ x: 1, y: 0 });
    expect(screen.getAllByRole("button")[1]).toHaveFocus();
    expect(first).toHaveAttribute("aria-pressed", "true");
  });
  it("renders accessible movement, attack, and enemy threat overlays", async () => {
    const view = render(
      <MapPanel
        battle={battle}
        selected={{ x: 0, y: 0 }}
        select={vi.fn()}
        empty=""
        yourSlot={1}
        selectedUnit={battle.units[0]}
        selectedUnitKey="unit-1"
      />,
    );
    const movementTile = screen.getByRole("button", {
      name: /Reachable movement tile.*\(1, 0\)/,
    });
    expect(movementTile).toHaveClass("reachable");
    expect(movementTile).not.toHaveClass("attackable");
    const attackToggle = screen.getByRole("button", {
      name: "Show attack range",
    });
    expect(attackToggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(attackToggle);
    const tile = screen.getByRole("button", {
      name: /Potential attack range.*\(1, 0\)/,
    });
    expect(tile).toHaveClass("attackable");
    expect(tile).toHaveClass("reachable");
    expect(
      screen.getByRole("button", { name: "Hide attack range" }),
    ).toHaveAttribute("aria-pressed", "true");
    view.rerender(
      <MapPanel
        battle={battle}
        selected={{ x: 0, y: 0 }}
        select={vi.fn()}
        empty=""
        yourSlot={1}
        selectedUnit={battle.units[1]}
        selectedUnitKey="unit-2"
      />,
    );
    expect(
      screen.getByRole("button", { name: "Show attack range" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.queryByRole("button", { name: /Potential attack range/ }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Show enemy threat area"));
    expect(
      screen.getByText(/future enemy choices are not shown/),
    ).toBeVisible();
    expect(
      screen.getAllByRole("button", {
        name: /Potentially threatened by observed enemies/,
      }).length,
    ).toBeGreaterThan(0);
  });
  it("shows observed unit data separately from baseline rules", () => {
    render(<UnitInspector unit={battle.units[0]} snapshot={snapshot} />);
    expect(screen.getByText("Health (internal)")).toBeVisible();
    expect(screen.getByText("Baseline rule information")).toBeVisible();
    expect(
      screen.getByText("Current CO effects may change baseline rules."),
    ).toBeVisible();
  });
  it("reports a successful health request to the native shell", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: "ok", emulator: "synthetic" })),
        ),
    );
    try {
      render(<Health />);
      await screen.findByText(/Connected/);
      expect(invoke).toHaveBeenCalledWith(
        "report_connection",
        expect.objectContaining({ connected: true }),
      );
    } finally {
      delete window.__TAURI__;
    }
  });
  it("shows unavailable-server guidance and lets the user retry", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "ok", emulator: "synthetic" })),
      );
    vi.stubGlobal("fetch", fetcher);
    render(<Health />);
    await screen.findByText(/Start the local server/);
    await userEvent.click(
      screen.getByRole("button", { name: "Check connection" }),
    );
    await screen.findByText(/Connected/);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("opens a snapshot and filters the rendered roster", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: "ok", emulator: "synthetic" })),
        ),
    );
    render(<App />);
    const file = new File([JSON.stringify(fixture)], "state.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve(JSON.stringify(fixture)),
    });
    await userEvent.upload(screen.getByLabelText("Open snapshot"), file);
    await waitFor(() =>
      expect(screen.getByText("Snapshot · read only")).toBeVisible(),
    );
    await userEvent.type(screen.getByLabelText("Filter units"), "Player 2");
    expect(document.querySelectorAll("#roster button")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Export snapshot" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Load matching screenshot" }),
    ).toBeDisabled();
  });
});

it.each([3, 4] as const)(
  "allows player slot %s to act with its own units",
  (slot) => {
    const selected = structuredClone(snapshot);
    const selectedBattle = selected.observation!.game_state.battle.value!;
    selectedBattle.active_player_slot = slot;
    selectedBattle.units[0].army_slot = slot;
    selectedBattle.units[0].used_this_turn = false;
    selectedBattle.units[0].embarked = false;
    selectedBattle.players = [1, 2, 3, 4].map((number) => ({
      ...selectedBattle.players[0],
      slot: number,
      team_id: number === 2 ? 1 : 0,
    }));
    const view: ViewState = {
      ...new MatchSession().getSnapshot(),
      snapshot: selected,
      connected: true,
      ready: true,
      identity: {
        contract_version: 1,
        role: "player",
        player_slot: slot === 3 ? "slot_3" : "slot_4",
        match_id: selected.summary.match_id,
      },
    };
    function Harness() {
      const model = useGameplay(view, vi.fn());
      return (
        <div data-testid="multiplayer">
          {JSON.stringify({
            ready: model.ready,
            ownsUnit: model.units.some(({ unit }) => unit.army_slot === slot),
            alliedTarget: model.targets.some((unit) => unit.army_slot === 1),
          })}
        </div>
      );
    }
    render(<Harness />);
    expect(screen.getByTestId("multiplayer")).toHaveTextContent('"ready":true');
    expect(screen.getByTestId("multiplayer")).toHaveTextContent(
      '"ownsUnit":true',
    );
    expect(screen.getByTestId("multiplayer")).toHaveTextContent(
      '"alliedTarget":false',
    );
  },
);
