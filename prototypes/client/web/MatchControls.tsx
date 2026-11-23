import { useRef } from "react";
import type { GameplayAction } from "./command_input";
import type { ViewState } from "./session";
import type { ActionKind, GameplayModel } from "./gameplay";
import { positionLabel } from "./gameplay";
import { ActionMenu, restoreBoardFocus } from "./ContextActions";
import { Sprite, useSpritePack } from "./sprites";
import { coName, unitLabel } from "./presentation";
import { powerMeterLabel, powerReadiness } from "./co_power";
import { unitName } from "./Board";
import catalog from "./catalog.json";

const confirmationLabels = {
  purchase: "Buy unit",
  activate_normal_power: "Activate normal Power",
  activate_super_power: "Activate Super Power",
  end_turn: "Confirm end turn",
  surrender: "Surrender match",
} as const;
const profileByName = (name: string) =>
  Object.entries(catalog.units).find(([, profile]) => profile.name === name);
type Props = {
  model: GameplayModel;
  view: ViewState;
  onSubmit: (action: GameplayAction, revision: number) => void;
};

export function ActionConfirmation({
  model,
  view,
  onSubmit,
  returnFocus,
}: Props & { returnFocus?: () => void }) {
  const { draft } = model;
  if (
    draft.phase !== "review" ||
    !draft.kind ||
    !(draft.kind in confirmationLabels) ||
    model.pending
  )
    return null;
  const kind = draft.kind as keyof typeof confirmationLabels;
  const point = draft.base ??
    model.destination ??
    model.battle?.map.tiles[0] ?? { x: 0, y: 0 };
  const player = model.battle?.players.find((item) => item.slot === model.slot);
  const price =
    kind === "purchase" ? profileByName(draft.unitType)?.[1].cost : undefined;
  const affordable =
    kind !== "purchase" ||
    (price !== undefined && player !== undefined && player.funds >= price);
  const back = () => {
    model.cancel();
    if (returnFocus) requestAnimationFrame(returnFocus);
    else restoreBoardFocus(point);
  };
  return (
    <ActionMenu
      key={kind}
      point={point}
      center
      label="Confirm action"
      onBack={back}
    >
      <div className="command-preview" aria-label="Action preview">
        <h3>{confirmationLabels[kind]}</h3>
        {kind === "purchase" ? (
          <p>
            Buy {draft.unitType} for {price?.toLocaleString() ?? "unknown"}{" "}
            funds at {positionLabel(point)}? Available funds:{" "}
            {player?.funds.toLocaleString() ?? "unknown"}.
          </p>
        ) : kind === "end_turn" ? (
          <div className="turn-confirmation">
            {model.units.length ? (
              <>
                <p>
                  End your turn with {model.units.length} ready unit
                  {model.units.length === 1 ? "" : "s"} unused?
                </p>
                <ul className="unused-unit-list" aria-label="Unused units">
                  {model.units.map(({ unit, id }) => (
                    <li key={id}>
                      {unitName(unit)} · {positionLabel(unit)}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p>No ready units remain unused. Pass the turn?</p>
            )}
          </div>
        ) : kind === "surrender" ? (
          <p role="alert" className="surrender-warning">
            Surrender will immediately forfeit this match. This action cannot be
            undone.
          </p>
        ) : (
          <p>
            Activate {player ? coName(player.co_id) : "your CO"}'s{" "}
            {kind === "activate_super_power" ? "Super Power" : "normal Power"}?
            Meter:{" "}
            {player ? powerMeterLabel(player.power_meter) : "unavailable"}.
            Readiness is checked before activation.
          </p>
        )}
        <div className="action-menu-buttons">
          <button
            id="submit-action"
            type="button"
            disabled={!model.action || !affordable}
            onClick={() => {
              if (model.action && affordable && view.snapshot) {
                onSubmit(model.action, view.snapshot.summary.revision);
                restoreBoardFocus(point);
              }
            }}
          >
            {kind === "purchase"
              ? `Buy ${draft.unitType}`
              : confirmationLabels[kind]}
          </button>
          <button type="button" onClick={back}>
            Back
          </button>
        </div>
      </div>
    </ActionMenu>
  );
}

export function MatchControls(props: Props) {
  const { model } = props;
  const trigger = useRef<HTMLButtonElement | null>(null);
  const player = model.battle?.players.find((item) => item.slot === model.slot);
  const choices: {
    kind: ActionKind;
    label: string;
    power?: "normal" | "super";
  }[] = [
    { kind: "activate_normal_power", label: "Power", power: "normal" },
    { kind: "activate_super_power", label: "Super Power", power: "super" },
    { kind: "end_turn", label: "End turn" },
    { kind: "surrender", label: "Surrender" },
  ];
  return (
    <>
      <div
        className="toolbar match-controls"
        role="group"
        aria-label="Match controls"
      >
        {choices.map((item) => {
          const readiness =
            item.power && player
              ? powerReadiness(player, item.power)
              : "unknown";
          return (
            <button
              key={item.kind}
              type="button"
              title={
                !model.available(item.kind)
                  ? model.feature(item.kind)?.unavailable_reason ||
                    "Unavailable on this server."
                  : readiness === "not_ready"
                    ? "CO Power is not ready."
                    : undefined
              }
              disabled={
                !model.editable ||
                !model.available(item.kind) ||
                (!!item.power && readiness === "not_ready")
              }
              onClick={(event) => {
                trigger.current = event.currentTarget;
                model.dispatch({ type: "choose", kind: item.kind });
              }}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {props.view.connected && model.unavailable && (
        <p className="hint" role="status">
          {model.unavailable}
        </p>
      )}
      {!model.draft.base && (
        <ActionConfirmation
          {...props}
          returnFocus={() => trigger.current?.focus()}
        />
      )}
    </>
  );
}

export function PurchaseMenu(props: Props) {
  const { model } = props;
  const { draft } = model;
  const pack = useSpritePack(!!draft.base);
  if (!draft.base || model.pending) return null;
  if (draft.kind === "purchase" && draft.phase === "review")
    return <ActionConfirmation {...props} />;
  if (draft.phase !== "select") return null;
  const player = model.battle?.players.find((item) => item.slot === model.slot);
  const back = () => {
    model.cancel();
    restoreBoardFocus(draft.base);
  };
  return (
    <ActionMenu point={draft.base} label="Purchase unit" onBack={back}>
      <h3>Production facility {positionLabel(draft.base)}</h3>
      <p>Funds: {player?.funds.toLocaleString() ?? "unavailable"}</p>
      <div className="action-menu-buttons">
        {model.purchaseUnitTypes.map((name) => {
          const profile = profileByName(name);
          const cost = profile?.[1].cost;
          const region =
            profile && pack?.units[`${profile[0]}:${model.slot ?? 1}`];
          const affordable =
            cost !== undefined && player !== undefined && player.funds >= cost;
          return (
            <button
              className="purchase-option"
              key={name}
              type="button"
              data-autofocus={draft.unitType === name || undefined}
              aria-pressed={draft.unitType === name}
              disabled={
                !model.editable ||
                model.occupiedBase ||
                !model.available("purchase") ||
                !affordable
              }
              onClick={() =>
                model.dispatch({ type: "purchase", unitType: name })
              }
            >
              <span className="purchase-icon" aria-hidden="true">
                {pack && region ? (
                  <Sprite
                    pack={pack}
                    region={region}
                    className="purchase-sprite"
                  />
                ) : (
                  unitLabel(Number(profile?.[0] ?? 0), name)
                )}
              </span>
              <span>
                {name}
                <small>
                  {cost !== undefined
                    ? `${cost.toLocaleString()} funds`
                    : "Price unavailable"}
                  {!affordable && cost !== undefined
                    ? " · Insufficient funds"
                    : ""}
                </small>
              </span>
            </button>
          );
        })}
      </div>
      <button type="button" onClick={back}>
        Back
      </button>
    </ActionMenu>
  );
}
