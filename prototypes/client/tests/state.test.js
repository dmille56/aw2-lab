import { readFileSync } from "node:fs";
import { describe, expect, it, afterEach, vi } from "vitest";
import { validateState } from "../web/state.js";
const fixture = () =>
  JSON.parse(
    readFileSync(new URL("./fixtures/state.json", import.meta.url), "utf8"),
  );
afterEach(() => vi.unstubAllGlobals());
describe("versioned snapshot boundary", () => {
  it("accepts a coherent snapshot and preserves observed zero values", () => {
    const state = fixture();
    expect(validateState(state)).toBe(state);
    expect(
      state.observation.game_state.battle.value.players[0].power_meter.value,
    ).toBe(0);
  });
  it.each([
    ["contract version", (s) => (s.contract_version = 99)],
    ["observation schema", (s) => (s.observation.schema_version = 99)],
    ["game schema", (s) => (s.observation.game_state.schema_version = 99)],
    ["boundary mismatch", (s) => s.observation.revision++],
    [
      "unsafe revision",
      (s) => (s.summary.revision = Number.MAX_SAFE_INTEGER + 1),
    ],
    ["invalid match identity", (s) => (s.summary.match_id = "../other")],
    [
      "duplicate map tile",
      (s) =>
        (s.observation.game_state.battle.value.map.tiles[1] =
          s.observation.game_state.battle.value.map.tiles[0]),
    ],
    [
      "oversized map",
      (s) => (s.observation.game_state.battle.value.map.width = 10000),
    ],
    [
      "tile outside map",
      (s) => (s.observation.game_state.battle.value.map.tiles[0].x = -1),
    ],
    [
      "invalid units",
      (s) => (s.observation.game_state.battle.value.units = [null]),
    ],
  ])("rejects %s", (_, change) => {
    const s = fixture();
    change(s);
    expect(() => validateState(s)).toThrow();
  });
  it("permits unavailable battle data without inventing an empty board", () => {
    const state = fixture();
    state.observation.game_state.battle = {
      status: "unavailable",
      value: null,
      reasons: ["Not in battle"],
    };
    expect(validateState(state).observation.game_state.battle.value).toBeNull();
  });
  it("permits a setup state without an observation", () => {
    const state = fixture();
    state.observation = null;
    expect(validateState(state).observation).toBeNull();
  });
});
describe("shared browser/native destination", () => {
  it.each([
    [false, ""],
    [true, "http://127.0.0.1:43127"],
  ])("selects destination for native=%s", async (native, expected) => {
    vi.resetModules();
    vi.stubGlobal("window", { __TAURI__: native });
    expect((await import("../web/transport.js")).API_BASE).toBe(expected);
  });
});
