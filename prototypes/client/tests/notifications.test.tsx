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
