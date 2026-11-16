import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { GameNotifications } from "../web/GameNotifications";
import {
  MatchSession,
  type CommandProgress,
  type ViewState,
} from "../web/session";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";
afterEach(cleanup);
const command = (
  phase: CommandProgress["phase"],
  id = "00000000-0000-4000-8000-000000000091",
): CommandProgress => ({
  request: {
    contract_version: 1,
    request_id: id,
    expected_revision: 1,
    action: { contract_version: 1, kind: "end_turn" },
  },
  receipt: null,
  result: null,
  phase,
});
const view = (phase: CommandProgress["phase"]): ViewState => ({
  ...new MatchSession().getSnapshot(),
  snapshot: validateState(structuredClone(fixture)),
  connected: true,
  ready: true,
  command: command(phase),
  error: "The match state changed.",
});
it("announces rejection, supports refresh/dismissal, and deduplicates repeated responses", async () => {
  const initial = view("rejected"),
    refresh = vi.fn();
  const rendered = render(
    <GameNotifications view={initial} onRefresh={refresh} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "End turn could not be executed",
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "The match state changed.",
  );
  await userEvent.click(screen.getByRole("button", { name: "Refresh board" }));
  expect(refresh).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: /Dismiss/ }));
  rendered.rerender(
    <GameNotifications view={{ ...initial, command: command("rejected") }} />,
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  rendered.rerender(
    <GameNotifications
      view={{
        ...initial,
        command: command("rejected", "00000000-0000-4000-8000-000000000092"),
      }}
    />,
  );
  expect(screen.getByRole("alert")).toBeVisible();
});
it.each([
  ["rolled_back", "Changes were undone"],
  ["recovery_required", "recover the match"],
  ["uncertain", "may have accepted"],
] as const)("explains %s outcomes", (phase, text) => {
  render(<GameNotifications view={view(phase)} />);
  expect(screen.getByRole("alert")).toHaveTextContent(text);
});
it("clears an unknown-outcome notice once the same request completes", () => {
  const initial = view("uncertain"),
    rendered = render(<GameNotifications view={initial} />);
  expect(screen.getByRole("alert")).toBeVisible();
  rendered.rerender(
    <GameNotifications view={{ ...initial, command: command("completed") }} />,
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

function turnView(active: number, day = 1): ViewState {
  const value = view("completed");
  value.command = null;
  value.identity = {
    contract_version: 1,
    match_id: fixture.summary.match_id,
    role: "player",
    player_slot: "slot_1",
  };
  value.snapshot!.observation!.game_state.battle.value!.active_player_slot =
    active;
  value.snapshot!.observation!.game_state.battle.value!.day = day;
  return value;
}
it("announces a new own turn once and retains deduplication across dismissal and reconnect", async () => {
  const rendered = render(<GameNotifications view={turnView(2)} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
  rendered.rerender(<GameNotifications view={turnView(1, 2)} />);
  expect(screen.getByText("Your turn")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Day 2");
  await userEvent.click(
    screen.getByRole("button", { name: "Dismiss Your turn" }),
  );
  rendered.rerender(<GameNotifications view={turnView(1, 2)} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
  rendered.rerender(
    <GameNotifications view={new MatchSession().getSnapshot()} />,
  );
  rendered.rerender(<GameNotifications view={turnView(1, 2)} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
  rendered.rerender(<GameNotifications view={turnView(1, 3)} />);
  expect(screen.getByText("Your turn")).toBeVisible();
  rendered.rerender(<GameNotifications view={turnView(2, 3)} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
});
it("uses the initial connection as baseline and never notifies snapshot readers or operators", () => {
  const rendered = render(<GameNotifications view={turnView(1)} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
  const imported = turnView(1, 2);
  imported.connected = false;
  rendered.rerender(<GameNotifications view={imported} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
  const operator = turnView(1, 3);
  operator.identity = {
    contract_version: 1,
    match_id: fixture.summary.match_id,
    role: "operator",
    player_slot: null,
  };
  rendered.rerender(<GameNotifications view={operator} />);
  expect(screen.queryByText("Your turn")).not.toBeInTheDocument();
});
