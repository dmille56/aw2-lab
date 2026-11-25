import type { VersusOutcome } from "./BoardTurn";
import { playerName } from "./presentation";
import type { StateResponse } from "./state";

const outcomeLabels: Record<VersusOutcome, string> = {
  win: "Victory",
  loss: "Defeat",
  draw: "Draw",
  unknown: "Unavailable",
};

function displayName(id: string) {
  return id
    .replaceAll("_", " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export function PostMatchSummary({
  snapshot,
  yourSlot,
}: {
  snapshot: StateResponse;
  yourSlot: number | null;
}) {
  const { configuration } = snapshot.summary;
  const game = snapshot.observation?.game_state;
  const finalDay = game?.versus_final_day;
  return (
    <section
      className="card post-match-summary"
      aria-labelledby="post-match-title"
    >
      <h2 id="post-match-title">Match summary</h2>
      <dl>
        <div>
          <dt>Map</dt>
          <dd>{displayName(configuration.map_id)}</dd>
        </div>
        <div>
          <dt>Final day</dt>
          <dd>{finalDay && finalDay > 0 ? finalDay : "Unavailable"}</dd>
        </div>
      </dl>
      <table aria-label="Player results">
        <thead>
          <tr>
            <th scope="col">Player</th>
            <th scope="col">CO</th>
            <th scope="col">Team</th>
            <th scope="col">Result</th>
          </tr>
        </thead>
        <tbody>
          {configuration.players.map((player) => {
            const slot = Number(player.slot.slice(5));
            const outcome = game?.versus_result?.find(
              (entry) => entry.slot === player.slot,
            )?.outcome;
            return (
              <tr key={player.slot}>
                <th scope="row">
                  Player {slot} · {playerName(snapshot, slot)}
                  {slot === yourSlot ? " · You" : ""}
                </th>
                <td>{displayName(player.co_id)}</td>
                <td>{player.team_id.toUpperCase()}</td>
                <td>{outcomeLabels[outcome ?? "unknown"]}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="hint">Match statistics unavailable.</p>
    </section>
  );
}
