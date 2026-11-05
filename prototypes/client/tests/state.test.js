import template from "./fixtures/state.json";
import { describe, expect, it, afterEach, vi } from "vitest";
import { validateState } from "../web/state";
const fixture = () => structuredClone(template);
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
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
      "missing inspector health",
      (s) =>
        delete s.observation.game_state.battle.value.units[0].internal_health,
    ],
    [
      "invalid player funds",
      (s) =>
        (s.observation.game_state.battle.value.players[0].funds = "invalid"),
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
    [false, true, ""],
    [true, true, "http://127.0.0.1:43127"],
    [false, false, ""],
    [true, false, ""],
  ])(
    "selects destination for native=%s, production=%s",
    async (native, production, expected) => {
      vi.resetModules();
      vi.stubEnv("PROD", production);
      vi.stubGlobal("window", { __TAURI__: native });
      expect((await import("../web/transport")).API_BASE).toBe(expected);
    },
  );
  it("uses the packaged native API port supplied by the host", async () => {
    vi.resetModules();
    vi.stubEnv("PROD", true);
    const invoke = vi.fn().mockResolvedValue("http://127.0.0.1:49381");
    vi.stubGlobal("window", { __TAURI__: { core: { invoke } } });
    const { getApiBase } = await import("../web/transport");
    await expect(getApiBase()).resolves.toBe("http://127.0.0.1:49381");
    expect(invoke).toHaveBeenCalledWith("client_api_base", {});
  });
});
