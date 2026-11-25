import type { BattleState } from "./state";
import type { components } from "./generated/api";

export type BoardTurnMode = "live" | "snapshot" | "unavailable";
export type VersusOutcome = components["schemas"]["VersusOutcome"];

const resultTitles: Record<VersusOutcome, string> = {
  win: "Victory",
  loss: "Defeat",
  draw: "Draw",
  unknown: "Match finished",
};

export function BoardTurn({
  battle,
  yourSlot,
  mode,
  finished = false,
  outcome = "unknown",
}: {
  battle: BattleState | null;
  yourSlot: number | null;
  mode: BoardTurnMode;
  finished?: boolean;
  outcome?: VersusOutcome;
}) {
  const active = battle?.players.some(
    (player) => player.slot === battle.active_player_slot,
  )
    ? battle.active_player_slot
    : null;
  const own =
    !finished && mode === "live" && active !== null && active === yourSlot;
  const title = finished
    ? resultTitles[outcome]
    : active === null || mode === "unavailable"
      ? "Turn unavailable"
      : own
        ? "Your turn"
        : `Player ${active}’s turn`;
  const context = [
    own ? `Player ${active}` : null,
    mode === "snapshot" ? "Snapshot · read only" : null,
    mode === "live" && !finished && active !== null && yourSlot !== null && !own
      ? "Not your turn"
      : null,
    battle ? `Day ${battle.day}` : null,
    finished && outcome === "unknown" ? "Result unavailable" : null,
    mode === "unavailable" ? "Connect or open a snapshot" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <h2
      id="board-turn"
      className={`board-turn${active !== null && !finished ? ` player-${active}` : ""}`}
      data-your-turn={own || undefined}
      data-match-result={finished ? outcome : undefined}
      aria-live="polite"
    >
      <span>{title}</span>
      {context && <small>{context}</small>}
    </h2>
  );
}
