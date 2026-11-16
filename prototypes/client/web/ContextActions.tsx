import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { GameplayAction } from "./command_input";
import type { ViewState } from "./session";
import type { ActionKind, GameplayModel } from "./gameplay";
import { unitName, type Position } from "./Board";

function focusTile(point: Position | null) {
  if (point)
    document
      .querySelector<HTMLButtonElement>(
        `#board button[data-x="${point.x}"][data-y="${point.y}"]`,
      )
      ?.focus();
}
export function ActionMenu({
  point,
  onBack,
  children,
  label,
}: {
  point: Position;
  onBack: () => void;
  children: ReactNode;
  label: string;
}) {
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({
    left: 8,
    top: 8,
    width: 260,
    maxHeight: 600,
  });
  useLayoutEffect(() => {
    const measure = () => {
      const tile = document
        .querySelector(
          `#board button[data-x="${point.x}"][data-y="${point.y}"]`,
        )
        ?.getBoundingClientRect();
      const rect = menu.current?.getBoundingClientRect();
      if (!tile || !rect) return;
      const zoom = Number(getComputedStyle(document.documentElement).zoom) || 1;
      const next = {
        width: Math.min(260, (window.innerWidth - 16) / zoom),
        maxHeight:
          (window.innerHeight * (window.innerWidth <= 600 ? 0.5 : 1) - 16) /
          zoom,
        left:
          Math.max(
            8,
            Math.min(tile.right + 8, window.innerWidth - rect.width - 8),
          ) / zoom,
        top:
          Math.max(
            8,
            Math.min(tile.top, window.innerHeight - rect.height - 8),
          ) / zoom,
      };
      setPosition((current) =>
        current.left === next.left &&
        current.top === next.top &&
        current.width === next.width &&
        current.maxHeight === next.maxHeight
          ? current
          : next,
      );
    };
    measure();
    menu.current
      ?.querySelector<HTMLButtonElement>("button:not(:disabled)")
      ?.focus();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    if (menu.current) observer?.observe(menu.current);
    observer?.observe(document.documentElement);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [point.x, point.y]);
  return (
    <div
      ref={menu}
      className="action-menu card"
      role="dialog"
      aria-label={label}
      style={position}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onBack();
        }
        if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
          const buttons = [
            ...(menu.current?.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ) ?? []),
          ];
          if (!buttons.length) return;
          event.preventDefault();
          const index = buttons.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          const next =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? buttons.length - 1
                : (index +
                    (event.key === "ArrowUp" ? -1 : 1) +
                    buttons.length) %
                  buttons.length;
          buttons[next]?.focus();
        }
      }}
    >
      {children}
    </div>
  );
}

export function ContextActions({
  model,
  view,
  onSubmit,
}: {
  model: GameplayModel;
  view: ViewState;
  onSubmit: (action: GameplayAction, revision: number) => void;
}) {
  const { draft } = model;
  const point = model.destination;
  if (
    !point ||
    !model.selectedUnit ||
    model.pending ||
    (draft.phase !== "menu" && !(draft.phase === "target" && draft.contextual))
  )
    return null;
  const back = () => {
    model.cancel();
    focusTile(draft.origin);
  };
  const send = (kind: ActionKind) => {
    const action = model.prepareAction(kind);
    if (action && view.snapshot)
      onSubmit(action, view.snapshot.summary.revision);
  };
  const attack = draft.path.length
    ? "move_attack"
    : model.available("attack")
      ? "attack"
      : "move_attack";
  return (
    <ActionMenu
      key={draft.phase}
      point={point}
      onBack={back}
      label="Unit actions"
    >
      <h3>
        {unitName(model.selectedUnit)} ·{" "}
        {Math.ceil(model.selectedUnit.internal_health / 10)} HP
      </h3>
      {draft.phase === "target" ? (
        <p role="status">Choose a highlighted enemy on the board.</p>
      ) : (
        <div className="action-menu-buttons">
          <button
            type="button"
            disabled={!model.prepareAction("move_wait")}
            onClick={() => send("move_wait")}
          >
            Wait
          </button>
          <button
            type="button"
            disabled={!model.prepareAction("move_capture")}
            onClick={() => send("move_capture")}
          >
            Capture
          </button>
          <button
            type="button"
            disabled={
              !model.editable ||
              !model.canAttack ||
              !model.movementReady ||
              !model.available(attack)
            }
            onClick={() => {
              model.dispatch({ type: "choose", kind: attack });
              requestAnimationFrame(() => focusTile(model.targets[0] ?? point));
            }}
          >
            Attack
          </button>
          <button
            type="button"
            disabled={!model.editable}
            onClick={() => {
              model.dispatch({ type: "plan" });
              focusTile(point);
            }}
          >
            Other actions / manual route
          </button>
        </div>
      )}
      <button type="button" onClick={back}>
        Back
      </button>
    </ActionMenu>
  );
}
