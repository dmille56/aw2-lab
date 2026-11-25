import "./PlayerHud.css";
import type { CSSProperties } from "react";
import type { BattleState, PlayerStats } from "./state";
import { useSpritePack } from "./sprites";
import { coName } from "./presentation";
import { PlayerMatchStats } from "./PlayerMatchStats";
import {
  activePowerLabel,
  powerMeterLabel,
  powerReadiness,
  powerCharge,
} from "./co_power";

export function PlayerHud({
  battle,
  yourSlot,
  stats,
  fogRestricted = battle.fog_enabled.value !== false,
}: {
  battle: BattleState;
  yourSlot: number | null;
  stats?: PlayerStats[] | null;
  fogRestricted?: boolean;
}) {
  const pack = useSpritePack(true);
  return (
    <div className="player-hud" aria-label="Player status">
      {battle.players.map((player) => {
        const name = coName(player.co_id),
          charge = powerCharge(player),
          portrait = pack?.portraits?.[String(player.co_id)];
        const fundsVisible = !fogRestricted || player.slot === yourSlot;
        const readiness =
          powerReadiness(player, "super") === "ready"
            ? "Super Power ready"
            : powerReadiness(player, "normal") === "ready"
              ? "Power ready"
              : activePowerLabel(player.active_power);
        return (
          <div
            key={player.slot}
            className={`hud-player player-${player.slot}${player.slot === battle.active_player_slot ? " active-player" : ""}${player.slot === yourSlot ? " your-player" : ""}`}
          >
            <strong className="hud-player-name">
              Player {player.slot}
              {player.slot === yourSlot ? " · You" : ""}
            </strong>
            <div className="hud-co" aria-label={`Commanding officer: ${name}`}>
              <span className="co-emblem" aria-hidden="true">
                {pack && portrait ? (
                  <span
                    className="co-portrait"
                    data-co-portrait={player.co_id}
                    style={{
                      width: portrait.width,
                      height: portrait.height,
                      backgroundImage: `url("${pack.image}")`,
                      backgroundSize: `${pack.width}px ${pack.height}px`,
                      backgroundPosition: `${-portrait.x}px ${-portrait.y}px`,
                    }}
                  />
                ) : (
                  name.slice(0, 2).toUpperCase()
                )}
              </span>
              <strong>{name}</strong>
            </div>
            <div className="hud-funds">
              <small>FUNDS</small>
              <strong>
                {fundsVisible ? (
                  <>
                    {player.funds.toLocaleString()}
                    <span aria-hidden="true"> G</span>
                    <span className="sr-only"> funds</span>
                  </>
                ) : (
                  "Unavailable"
                )}
              </strong>
            </div>
            <PlayerMatchStats
              stats={
                fogRestricted && player.slot !== yourSlot
                  ? undefined
                  : stats?.find((entry) => entry.slot === `slot_${player.slot}`)
              }
            />
            <div className="hud-charge">
              {charge ? (
                <div
                  className="power-stars"
                  role="progressbar"
                  aria-label={`${name} CO power charge`}
                  aria-valuemin={0}
                  aria-valuemax={charge.maximum}
                  aria-valuenow={Math.min(charge.value, charge.maximum)}
                  aria-valuetext={`${powerMeterLabel(player.power_meter)} · ${readiness}`}
                >
                  {Array.from({ length: charge.superStars }, (_, index) => (
                    <span
                      key={index}
                      aria-hidden="true"
                      className={`power-star${index >= charge.normalStars ? " super-star" : ""}${index === charge.normalStars ? " power-divider" : ""}`}
                      style={
                        {
                          "--charge": `${Math.max(0, Math.min(1, charge.value / charge.perStar - index)) * 100}%`,
                        } as CSSProperties
                      }
                    >
                      ★<span>★</span>
                    </span>
                  ))}
                </div>
              ) : (
                <span className="charge-unknown">
                  Charge threshold unavailable ·{" "}
                  {powerMeterLabel(player.power_meter)}
                </span>
              )}
              <span
                className={`power-readiness${readiness.includes("ready") ? " power-ready" : ""}`}
              >
                {readiness}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
