import type { ViewState } from "./session";
import { actionLabels } from "./CommandFeedback";
import "./ActionProgress.css";
export function ActionProgress({ view }: { view: ViewState }) {
  const command = view.command;
  const busy =
    !!command &&
    ["submitting", "queued", "running", "uncertain"].includes(command.phase);
  const label = command ? actionLabels[command.request.action.kind] : "Action";
  return (
    <div
      className="action-progress"
      role="status"
      aria-live="polite"
      hidden={!busy}
    >
      <span
        className={
          command?.phase === "uncertain"
            ? "progress-unknown"
            : "loading-spinner"
        }
        aria-hidden="true"
      >
        {command?.phase === "uncertain" ? "?" : ""}
      </span>
      <div>
        <strong>
          {command?.phase === "submitting"
            ? `Sending ${label}…`
            : command?.phase === "queued"
              ? `${label} accepted · waiting for the game…`
              : command?.phase === "uncertain"
                ? `${label}: outcome unknown`
                : `Executing ${label}…`}
        </strong>
        <p>
          {command?.phase === "uncertain"
            ? "The game may have accepted this action. Check its status before trying again."
            : "Please wait. You can inspect the board while the game finishes."}
        </p>
        <a href="#command-feedback">Action details and recovery</a>
      </div>
    </div>
  );
}
