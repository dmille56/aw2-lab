import catalog from "./catalog.json";
import type { StateResponse } from "./state";
import type { MatchIdentity } from "./session";

const terrainLabels: Record<string, string> = {
  Unused: "N/A",
  "Minicannon South": "MC.S",
  "Minicannon North": "MC.N",
  "Minicannon West": "MC.W",
  "Minicannon East": "MC.E",
  Laser: "LASR",
  "Black Cannon South": "BC.S",
  "Black Cannon North": "BC.N",
  Volcano: "VOLC",
  "Black Hole Factory": "BH.F",
  Deathray: "RAY",
  "Unused Blocked": "N/A",
  Empty: "—",
  Plain: "PLN",
  River: "RIV",
  Mountain: "MTN",
  Wood: "WOOD",
  Road: "RD",
  City: "CITY",
  Sea: "SEA",
  HQ: "HQ",
  Airport: "AIR",
  Port: "PORT",
  Bridge: "BRG",
  Shoal: "SHL",
  Base: "BASE",
  Pipe: "PIPE",
  "Pipe Seam": "SEAM",
  "Missile Silo": "SILO",
  "Spent Silo": "USED",
  Reef: "REEF",
  Lab: "LAB",
};
const unitLabels: Record<string, string> = {
  Infantry: "INF",
  Mech: "MECH",
  "Medium Tank": "MD.T",
  Tank: "TANK",
  Recon: "RECN",
  APC: "APC",
  Neotank: "NEO",
  Artillery: "ART",
  Rockets: "RKT",
  "Anti-Air": "AA",
  Missiles: "MSL",
  Fighter: "FTR",
  Bomber: "BMB",
  "Battle Copter": "B.C",
  "Transport Copter": "T.C",
  Battleship: "B.S",
  Cruiser: "CRS",
  Lander: "LDR",
  Submarine: "SUB",
};
export const terrainLabel = (id: number, name: string) =>
  terrainLabels[name] ?? `T${id}`;
export const unitLabel = (id: number, name: string) =>
  unitLabels[name] ?? `U${id}`;
export const coName = (id: number) =>
  (catalog.cos as Record<number, string>)[id] ?? `Unknown CO (ID ${id})`;
export const playerName = (snapshot: StateResponse, slot: number) =>
  snapshot.summary.slots
    .find((player) => player.slot === `slot_${slot}`)
    ?.display_name?.trim() || "Unknown player";
export const humanSlot = (identity: MatchIdentity | null) =>
  identity?.role === "player" && identity.player_slot
    ? Number(identity.player_slot.slice(5))
    : null;
export function perspective(
  snapshot: StateResponse,
  identity: MatchIdentity | null,
  live: boolean,
) {
  if (!live) return "Snapshot · no authenticated player perspective";
  if (identity?.role === "operator") return "Operator view · no player slot";
  const slot = humanSlot(identity);
  return slot
    ? `You: Player ${slot} · ${playerName(snapshot, slot)}`
    : "Your player slot is unknown · server identity unavailable";
}
export function fitTileSize(
  width: number,
  height: number,
  columns: number,
  rows: number,
  minimum = 36,
) {
  // Preserve legible labels; huge maps retain scrolling rather than shrinking text away.
  return Math.max(
    minimum,
    Math.min(
      90,
      Math.floor(
        Math.min((width - columns + 1) / columns, (height - rows + 1) / rows),
      ),
    ),
  );
}
