import type { BattleState } from "./state";

export type BoardTurnMode = "live" | "snapshot" | "unavailable";

export function BoardTurn({
  battle,
  yourSlot,
  mode,
  finished = false,
}: {
  battle: BattleState | null;
  yourSlot: number | null;
  mode: BoardTurnMode;
  finished?: boolean;
}) {
  const active = battle?.players.some(
    (player) => player.slot === battle.active_player_slot,
  )
    ? battle.active_player_slot
    : null;
  const own =
    !finished && mode === "live" && active !== null && active === yourSlot;
  const title = finished
    ? "Match finished"
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
    mode === "unavailable" ? "Connect or open a snapshot" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <h2
      id="board-turn"
      className={`board-turn${active !== null && !finished ? ` player-${active}` : ""}`}
      data-your-turn={own || undefined}
    >
      <span>{title}</span>
      <small>{context}</small>
    </h2>
  );
}
