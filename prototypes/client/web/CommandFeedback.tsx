import { useEffect, useRef, useState } from "react";
import type { CommandProgress, ViewState } from "./session";
import type { ActionKind } from "./gameplay";
const labels: Record<ActionKind, string> = {
  move_wait: "Wait",
  attack: "Attack in place",
  move_attack: "Attack",
  move_capture: "Capture",
  join: "Join units",
  supply: "Supply",
  dive: "Dive",
  rise: "Rise",
  silo_launch: "Launch missile",
  load: "Load",
  unload: "Unload",
  purchase: "Purchase unit",
  activate_normal_power: "Activate normal Power",
  activate_super_power: "Activate Super Power",
  end_turn: "End turn",
  surrender: "Surrender",
};

export function CommandFeedback({
  view,
  onRetry,
  onCheckStatus,
}: {
  view: ViewState;
  onRetry: () => void;
  onCheckStatus: () => void;
}) {
  const command = view.command;
  const activityMatch = useRef(view.snapshot?.summary.match_id ?? null);
  const [activity, setActivity] = useState<CommandProgress[]>([]);
  useEffect(() => {
    const matchId = view.snapshot?.summary.match_id ?? null;
    if (activityMatch.current === matchId) return;
    activityMatch.current = matchId;
    setActivity([]);
  }, [view.snapshot?.summary.match_id]);
  useEffect(() => {
    if (!command) return;
    setActivity((previous) => {
      const existing = previous.findIndex(
        (item) => item.request.request_id === command.request.request_id,
      );
      const updated = [...previous];
      if (existing >= 0) updated[existing] = command;
      else updated.push(command);
      return updated.slice(-8);
    });
  }, [command]);
  const activityEntries = command
    ? [
        ...activity.filter(
          (item) => item.request.request_id !== command.request.request_id,
        ),
        command,
      ].slice(-8)
    : activity;
  return (
    <div className="command-feedback">
      {command && (
        <section
          className="card command-activity"
          aria-label="Command activity"
        >
          <h3>Command activity</h3>
          <div
            className="command-result"
            aria-live="polite"
            data-status={command.phase}
          >
            <p className="activity-action">
              {labels[command.request.action.kind]}
            </p>
            <h4>Command status: {command.phase}</h4>
            <p className="activity-message" role="status">
              {command.phase === "submitting"
                ? "Sending this action to the match."
                : command.phase === "uncertain"
                  ? "The server may have accepted this action. Check its status or retry safely with the same request."
                  : command.phase === "queued" || command.phase === "running"
                    ? "Accepted by the server; waiting for the emulator to finish."
                    : command.phase === "completed"
                      ? "Completed and committed to the match."
                      : command.phase === "rolled_back"
                        ? "The action was rolled back. Its movement and other changes were undone; the board refreshes to the restored game state."
                        : "The action did not complete. Review the result details."}
            </p>
            <details className="command-metadata">
              <summary>Command details</summary>
              <p>
                Request {command.request.request_id} · expected revision{" "}
                {command.request.expected_revision}
              </p>
              {command.receipt && (
                <p>
                  Accepted as {command.receipt.command_id} · accepted revision{" "}
                  {command.receipt.accepted_revision}
                </p>
              )}
              {command.result?.resulting_revision !== null &&
                command.result?.resulting_revision !== undefined && (
                  <p>Resulting revision {command.result.resulting_revision}</p>
                )}
            </details>
            {command.result?.error && (
              <details className="command-error-details">
                <summary>
                  {command.result.error.code}: {command.result.error.message}
                </summary>
                <pre>
                  {JSON.stringify(command.result.error.details, null, 2)}
                </pre>
              </details>
            )}
            {command.phase === "uncertain" && (
              <button
                type="button"
                onClick={onRetry}
                disabled={!view.connected}
              >
                Retry safely with the same request ID
              </button>
            )}
            {command.receipt &&
              ["queued", "running"].includes(command.phase) && (
                <button
                  type="button"
                  onClick={onCheckStatus}
                  disabled={!view.connected}
                >
                  Check command status
                </button>
              )}
          </div>
          {activityEntries.length > 1 && (
            <details className="command-history">
              <summary>Previous actions ({activityEntries.length - 1})</summary>
              <ol>
                {activityEntries
                  .filter(
                    (item) =>
                      item.request.request_id !== command.request.request_id,
                  )
                  .reverse()
                  .map((item) => (
                    <li key={item.request.request_id}>
                      <span className="activity-action">
                        {labels[item.request.action.kind]}
                      </span>
                      <strong>Command status: {item.phase}</strong>
                      <p>
                        Request {item.request.request_id} · expected revision{" "}
                        {item.request.expected_revision}
                      </p>
                      {item.receipt && (
                        <p>
                          Accepted as {item.receipt.command_id} · accepted
                          revision {item.receipt.accepted_revision}
                        </p>
                      )}
                      {item.result?.resulting_revision !== null &&
                        item.result?.resulting_revision !== undefined && (
                          <p>
                            Resulting revision {item.result.resulting_revision}
                          </p>
                        )}
                      {item.result?.error && (
                        <details className="command-error-details">
                          <summary>
                            {item.result.error.code}:{" "}
                            {item.result.error.message}
                          </summary>
                          <pre>
                            {JSON.stringify(item.result.error.details, null, 2)}
                          </pre>
                        </details>
                      )}
                    </li>
                  ))}
              </ol>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
