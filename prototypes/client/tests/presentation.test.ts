import { expect, it } from "vitest";
import {
  coName,
  fitTileSize,
  humanSlot,
  perspective,
  playerName,
  terrainLabel,
  unitLabel,
} from "../web/presentation";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";
const state = validateState(fixture);
it("fits width and height, preserves legibility, and supports coordinate space", () => {
  expect(fitTileSize(900, 600, 16, 15)).toBe(39);
  expect(fitTileSize(320, 600, 16, 15)).toBe(36);
  expect(fitTileSize(900, 600, 16, 15, 44)).toBe(44);
  expect(fitTileSize(900, 600, 2, 2)).toBe(90);
});
it("keeps names and unknown numeric identities explicit", () => {
  expect(coName(1)).toBe("Andy");
  expect(coName(2)).toBe("Max");
  expect(coName(18)).toBe("Unknown CO (ID 18)");
  expect(playerName(state, 1)).toBe("one");
  expect(playerName(state, 8)).toBe("Unknown player");
  expect(terrainLabel(8, "HQ")).toBe("HQ");
  expect(terrainLabel(999, "Terrain 999")).toBe("T999");
  expect(unitLabel(1, "Infantry")).toBe("INF");
  expect(unitLabel(999, "Unit 999")).toBe("U999");
});
it("never infers a human slot from turn, snapshot, or operator role", () => {
  expect(humanSlot(null)).toBeNull();
  expect(perspective(state, null, false)).toContain(
    "no authenticated player perspective",
  );
  expect(perspective(state, null, true)).toContain("unknown");
  const operator = {
    contract_version: 1 as const,
    match_id: state.summary.match_id,
    role: "operator" as const,
    player_slot: null,
  };
  expect(humanSlot(operator)).toBeNull();
  expect(perspective(state, operator, true)).toBe(
    "Operator view · no player slot",
  );
  const player = {
    ...operator,
    role: "player" as const,
    player_slot: "slot_2" as const,
  };
  expect(humanSlot(player)).toBe(2);
  expect(perspective(state, player, true)).toBe("You: Player 2 · two");
});
