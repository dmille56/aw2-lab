import { createPortal } from "react-dom";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { GameplayAction } from "./command_input";
import { waitLabel } from "./action_labels";
import { DamagePreview } from "./DamagePreview";
import type { ViewState } from "./session";
import { sameTile, type ActionKind, type GameplayModel } from "./gameplay";
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
  center = false,
}: {
  point: Position;
  center?: boolean;
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
      if (!rect || (!tile && !center)) return;
      const zoom = Number(getComputedStyle(document.documentElement).zoom) || 1;
      const next = {
        width: Math.min(260, (window.innerWidth - 16) / zoom),
        maxHeight:
          (window.innerHeight * (window.innerWidth <= 600 ? 0.5 : 1) - 16) /
          zoom,
        left:
          Math.max(
            8,
            Math.min(
              center ? (window.innerWidth - rect.width) / 2 : tile!.right + 8,
              window.innerWidth - rect.width - 8,
            ),
          ) / zoom,
        top:
          Math.max(
            8,
            Math.min(
              center ? (window.innerHeight - rect.height) / 2 : tile!.top,
              window.innerHeight - rect.height - 8,
            ),
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
    (
      menu.current?.querySelector<HTMLButtonElement>(
        "button[data-autofocus]:not(:disabled)",
      ) ??
      menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")
    )?.focus();
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
  }, [point.x, point.y, center]);
  return createPortal(
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
    </div>,
    document.body,
  );
}

export function restoreBoardFocus(point: Position | null) {
  queueMicrotask(() => {
    const action = document.querySelector<HTMLButtonElement>(
      ".action-menu button:not(:disabled)",
    );
    if (action) action.focus();
    else focusTile(point);
  });
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
  const point = draft.phase === "enemy_menu" ? draft.target : model.destination;
  const selectingTarget = draft.phase === "target" && draft.contextual;
  const selectingMissileTarget =
    selectingTarget && draft.kind === "silo_launch";
  const firstAttackTarget =
    selectingTarget && !selectingMissileTarget
      ? model.attackableTargets[0]
      : undefined;
  useLayoutEffect(() => {
    if (firstAttackTarget) focusTile(firstAttackTarget);
  }, [firstAttackTarget]);
  useLayoutEffect(() => {
    if (
      draft.contextual &&
      draft.phase === "review" &&
      draft.kind === "unload" &&
      !draft.unloadPassengerId &&
      Object.keys(draft.dropDestinations).length
    )
      document.querySelector<HTMLButtonElement>("#unload-confirm")?.focus();
  }, [
    draft.contextual,
    draft.phase,
    draft.kind,
    draft.unloadPassengerId,
    draft.dropDestinations,
  ]);
  const unloading =
    draft.phase === "review" && draft.kind === "unload" && draft.contextual;
  if (
    !point ||
    !model.selectedUnit ||
    model.pending ||
    (draft.phase !== "menu" &&
      draft.phase !== "enemy_menu" &&
      !selectingMissileTarget &&
      !unloading)
  )
    return null;
  const back = () => {
    model.cancel();
    restoreBoardFocus(draft.origin);
  };
  const send = (kind: ActionKind, target: Position | null = null) => {
    const action = model.prepareAction(kind, target);
    if (action && view.snapshot)
      onSubmit(action, view.snapshot.summary.revision);
  };
  const attack = model.attackKind;
  if (draft.phase === "enemy_menu") {
    const enemy = model.attackableTargets.find((unit) => sameTile(unit, point));
    if (!enemy) return null;
    return (
      <ActionMenu point={point} onBack={back} label="Attack enemy">
        <h3>Attack {unitName(enemy)}</h3>
        <p>
          Target ({point.x}, {point.y}). Your planned route is retained.
        </p>
        {model.battle && (
          <DamagePreview
            battle={model.battle}
            attacker={model.selectedUnit}
            defender={enemy}
            path={draft.path}
          />
        )}
        <button
          type="button"
          aria-describedby="attack-damage-preview"
          disabled={!model.prepareAction(attack, point)}
          onClick={() => send(attack, point)}
        >
          Attack
        </button>
        <button type="button" onClick={back}>
          Cancel
        </button>
      </ActionMenu>
    );
  }
  const chooseTarget = (kind: ActionKind) => {
    model.dispatch({ type: "choose", kind });
    if (kind === "silo_launch") requestAnimationFrame(() => focusTile(point));
  };
  const silo =
    [1, 2].includes(model.selectedUnit.unit_type) &&
    model.battle?.map.tiles.some(
      (tile) =>
        tile.x === point.x && tile.y === point.y && tile.terrain_class === 17,
    );
  const choices: { kind: ActionKind; label: string; show: boolean }[] = [
    {
      kind: "move_wait",
      label: waitLabel(draft.path.length),
      show: model.movementReady,
    },
    { kind: "move_capture", label: "Capture", show: model.canCapture },
    { kind: "join", label: "Join", show: model.canJoin },
    {
      kind: "supply",
      label: "Supply",
      show: model.canSupply && model.movementReady,
    },
    {
      kind: "dive",
      label: "Dive",
      show:
        model.selectedUnit.unit_type === 24 &&
        !model.selectedUnit.submerged &&
        model.movementReady,
    },
    {
      kind: "rise",
      label: "Rise",
      show:
        model.selectedUnit.unit_type === 24 &&
        !!model.selectedUnit.submerged &&
        model.movementReady,
    },
    {
      kind: "load",
      label: "Load",
      show:
        !!model.loadTransport &&
        model.loadTransport.reference !== model.selectedUnit.reference,
    },
  ];
  const missing = choices.filter(
    (item) => item.show && !model.available(item.kind),
  );
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
      {selectingMissileTarget ? (
        <p role="status">
          Choose a missile target on the board. A 3×3 area is hit.
        </p>
      ) : unloading ? (
        <>
          <p>Choose a passenger, then a highlighted drop tile.</p>
          {model.unloadDropOptions.map((item, index) => {
            const drop = draft.dropDestinations[item.id];
            const destinations = item.destinations.filter(
              (point) =>
                !Object.entries(draft.dropDestinations).some(
                  ([id, other]) => id !== item.id && sameTile(point, other),
                ),
            );
            return (
              <div className="cargo-choice" key={item.id}>
                <button
                  type="button"
                  aria-pressed={draft.unloadPassengerId === item.id}
                  disabled={!model.editable || !destinations.length}
                  onClick={() => {
                    model.dispatch({
                      type: "unload_passenger",
                      unitId: item.id,
                    });
                    requestAnimationFrame(() =>
                      focusTile(drop ?? destinations[0] ?? point),
                    );
                  }}
                >
                  Passenger {index + 1}: {unitName(item.unit)}
                </button>
                <span>
                  {drop
                    ? `Drop ${index + 1}: (${drop.x},${drop.y})`
                    : "No drop selected"}
                </span>
                {drop && (
                  <button
                    type="button"
                    onClick={() => {
                      model.dispatch({
                        type: "drop_destination",
                        unitId: item.id,
                        point: null,
                      });
                      restoreBoardFocus(point);
                    }}
                  >
                    Clear drop {index + 1}
                  </button>
                )}
              </div>
            );
          })}
          <p role="status">{model.unloadError}</p>
          <button
            id="unload-confirm"
            type="button"
            disabled={!model.prepareAction("unload")}
            onClick={() => send("unload")}
          >
            Unload selected cargo
          </button>
        </>
      ) : (
        <div className="action-menu-buttons">
          {choices
            .filter((item) => item.show)
            .map((item) => (
              <button
                key={item.kind}
                type="button"
                title={
                  !model.available(item.kind)
                    ? model.feature(item.kind)?.unavailable_reason ||
                      "Unavailable on this server."
                    : undefined
                }
                disabled={!model.prepareAction(item.kind)}
                onClick={() => send(item.kind)}
              >
                {item.label}
              </button>
            ))}
          {model.canAttack && model.movementReady && (
            <button
              type="button"
              disabled={!model.editable || !model.available(attack)}
              onClick={() => chooseTarget(attack)}
            >
              Attack
            </button>
          )}
          {silo && (
            <button
              type="button"
              disabled={!model.siloReady || !model.movementReady}
              onClick={() => chooseTarget("silo_launch")}
            >
              Launch missile
            </button>
          )}
          {!!model.selectedTransportCargo.length && (
            <button
              type="button"
              disabled={
                !model.editable ||
                !model.available("unload") ||
                !model.movementReady ||
                model.unloadDropOptions.every(
                  (item) => !item.destinations.length,
                )
              }
              onClick={() => model.dispatch({ type: "choose", kind: "unload" })}
            >
              Unload
            </button>
          )}
          <button
            type="button"
            disabled={!model.editable}
            onClick={() => {
              model.dispatch({ type: "plan" });
              focusTile(point);
            }}
          >
            Edit route manually
          </button>
          {!!missing.length && (
            <details>
              <summary>Unavailable actions</summary>
              {missing.map((item) => (
                <p key={item.kind}>
                  {item.label}:{" "}
                  {model.feature(item.kind)?.unavailable_reason ||
                    "Not available on this server."}
                </p>
              ))}
            </details>
          )}
        </div>
      )}
      <button type="button" onClick={back}>
        Back
      </button>
    </ActionMenu>
  );
}
