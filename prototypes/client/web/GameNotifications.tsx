import { useEffect, useRef, useState } from "react";
import { humanSlot } from "./presentation";
import type { ViewState } from "./session";
import { actionLabel } from "./action_labels";
import "./GameNotifications.css";
export type Notice = {
  id: string;
  title: string;
  message: string;
  kind: "error" | "warning" | "turn";
};
export function GameNotifications({
  view,
  onRefresh,
}: {
  view: ViewState;
  onRefresh?: () => void;
}) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const seen = useRef(new Set<string>());
  const match = useRef(view.snapshot?.summary.match_id);
  const turns = useRef(new Map<string, Set<string>>());
  const turnIdentity = useRef<string | null>(null);
  const battle = view.snapshot?.observation?.game_state.battle.value;
  const playerSlot = humanSlot(view.identity);
  const turnMatchId = view.snapshot?.summary.match_id;
  const playable = view.snapshot?.summary.lifecycle === "playable";
  const day = battle?.day;
  const activePlayer = battle?.active_player_slot;
  useEffect(() => {
    if (
      !view.connected ||
      !view.ready ||
      !turnMatchId ||
      day === undefined ||
      activePlayer === undefined ||
      !playerSlot ||
      !playable
    ) {
      setNotices((previous) => previous.filter((item) => item.kind !== "turn"));
      return;
    }
    const identity = `${turnMatchId}:${playerSlot}`;
    const key = `${identity}:${day}:${activePlayer}`;
    const ownTurn = activePlayer === playerSlot;
    if (turnIdentity.current !== identity) {
      turnIdentity.current = identity;
      setNotices((previous) => previous.filter((item) => item.kind !== "turn"));
    }
    setNotices((previous) =>
      previous.filter(
        (item) => item.kind !== "turn" || (ownTurn && item.id === key),
      ),
    );
    const observed = turns.current.get(identity);
    if (!observed) {
      // The initial connection establishes a baseline, not a new turn event.
      turns.current.set(identity, new Set([key]));
      return;
    }
    if (!ownTurn || observed.has(key)) return;
    observed.add(key);
    if (observed.size > 256) {
      const oldest = observed.values().next().value;
      if (oldest) observed.delete(oldest);
    }
    const notice: Notice = {
      id: key,
      kind: "turn",
      title: "Your turn",
      message: `Day ${day} · Player ${playerSlot}. Choose a unit on the board.`,
    };
    setNotices((previous) =>
      [...previous.filter((item) => item.kind !== "turn"), notice].slice(-4),
    );
  }, [
    view.connected,
    view.ready,
    turnMatchId,
    playable,
    day,
    activePlayer,
    playerSlot,
  ]);

  useEffect(() => {
    const matchId = view.snapshot?.summary.match_id;
    if (match.current !== matchId) {
      match.current = matchId;
      seen.current.clear();
      setNotices([]);
    }
    const command = view.command;
    if (!command) return;
    const requestId = command.request.request_id;
    if (command.phase === "completed") {
      setNotices((previous) =>
        previous.filter((item) => item.id !== `${requestId}:uncertain`),
      );
      return;
    }
    if (
      !["rejected", "rolled_back", "recovery_required", "uncertain"].includes(
        command.phase,
      )
    )
      return;
    const id = `${requestId}:${command.phase}`;
    if (seen.current.has(id)) return;
    seen.current.add(id);
    const action = actionLabel(command.request.action);
    const reason = command.result?.error?.message || view.error;
    const notice: Notice = {
      id,
      kind: command.phase === "uncertain" ? "warning" : "error",
      title:
        command.phase === "rolled_back"
          ? `${action} was rolled back`
          : command.phase === "recovery_required"
            ? `${action} needs recovery`
            : command.phase === "uncertain"
              ? `${action}: outcome unknown`
              : `${action} could not be executed`,
      message:
        command.phase === "rolled_back"
          ? `Changes were undone. ${reason || "The board has been restored."} Review the action before trying again.`
          : command.phase === "recovery_required"
            ? `${reason || "The game could not restore a safe state."} Ask the match operator to recover the match before continuing.`
            : command.phase === "uncertain"
              ? "The server may have accepted this action. Check its status or use the safe retry in action details."
              : `${reason || "The game rejected this action."} Review your selection and the current board.`,
    };
    setNotices((previous) =>
      [
        ...previous.filter((item) => !item.id.startsWith(requestId + ":")),
        notice,
      ].slice(-4),
    );
  }, [view.command, view.error, view.snapshot?.summary.match_id]);
  return notices.length ? (
    <section className="game-notifications" aria-label="Notifications">
      {notices.map((notice) => (
        <article
          key={notice.id}
          className={`game-toast toast-${notice.kind}`}
          role={notice.kind === "turn" ? "status" : "alert"}
        >
          <div>
            <strong>{notice.title}</strong>
            <p>{notice.message}</p>
            {notice.kind !== "turn" && (
              <a href="#command-feedback">Action details and recovery</a>
            )}
            {notice.kind === "error" && onRefresh && (
              <button type="button" onClick={onRefresh}>
                Refresh board
              </button>
            )}
          </div>
          <button
            type="button"
            aria-label={`Dismiss ${notice.title}`}
            onClick={() =>
              setNotices((previous) =>
                previous.filter((item) => item.id !== notice.id),
              )
            }
          >
            ×
          </button>
        </article>
      ))}
    </section>
  ) : null;
}
