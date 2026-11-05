import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { Board, UnitInspector } from "../web/Board";
import { Health } from "../web/Health";
import { App } from "../web/App";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";
const snapshot = validateState(fixture);
const battle = snapshot.observation?.game_state.battle.value;
if (!battle) throw new Error("Fixture has no battle");
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("React viewer", () => {
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
