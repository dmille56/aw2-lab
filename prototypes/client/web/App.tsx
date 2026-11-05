import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { MapPanel } from "./MapPanel";
import { coName, humanSlot, perspective, playerName } from "./presentation";
import { Health } from "./Health";
import { MatchSession } from "./session";
import {
  applyTheme,
  readThemePreference,
  saveThemePreference,
  THEMES,
  type Appearance,
  type ThemeId,
} from "./appearance";
import {
  Details,
  UnitInspector,
  observed,
  owner,
  terrainName,
  unitName,
  type Position,
} from "./Board";

export function App() {
  const [session] = useState(() => new MatchSession());
  const view = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const [selected, setSelected] = useState<Position | null>(null);
  const [cargo, setCargo] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [themePreference, setThemePreference] = useState(readThemePreference);
  const tokenInput = useRef<HTMLInputElement>(null);
  const clearToken = () => {
    if (tokenInput.current) tokenInput.current.value = "";
  };
  useEffect(() => {
    if (!view.connected && tokenInput.current) tokenInput.current.value = "";
  }, [view.connected]);
  useEffect(() => () => session.disconnect(), [session]);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () =>
      applyTheme(
        document.documentElement,
        themePreference,
        media?.matches ?? false,
      );
    update();
    saveThemePreference(themePreference);
    if (themePreference.appearance !== "system" || !media) return;
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [themePreference]);
  const snapshot = view.snapshot,
    obs = snapshot?.observation;
  const battle =
    obs?.game_state.battle.status === "available"
      ? obs.game_state.battle.value
      : null;
  const cargoUnit = battle?.units.find((item) => item.reference === cargo);
  const tile = battle?.map.tiles.find(
    (t) => t.x === selected?.x && t.y === selected.y,
  );
  const unit = battle?.units.find(
    (u) => u.x === tile?.x && u.y === tile.y && !u.embarked,
  );
  const select = (position: Position) => {
    setSelected(position);
    setCargo(null);
  };
  const empty = !snapshot
    ? "Connect or open an exported StateResponse JSON file to see the board."
    : obs
      ? `Battle ${observed(obs.game_state.battle)}`
      : "No committed observation available.";
  return (
    <>
      <header>
        <div>
          <span className="eyebrow">AW2 LAB</span>
          <h1>Match viewer</h1>
        </div>
        <p id="connection" role="status">
          {view.status}
        </p>
      </header>
      <main>
        <Health />
        <section className="card setup" aria-label="Open match">
          <form
            id="connect"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget,
                data = new FormData(form);
              const id = data.get("match-id"),
                token = data.get("token");
              const input = form.elements.namedItem("token");
              if (input instanceof HTMLInputElement) input.value = "";
              setSelected(null);
              setCargo(null);
              if (typeof id === "string" && typeof token === "string")
                void session.connect(id, token);
            }}
          >
            <label>
              Match ID
              <input
                type="text"
                id="match-id"
                name="match-id"
                required
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <label>
              Player token
              <input
                ref={tokenInput}
                id="token"
                name="token"
                type="password"
                required
                autoComplete="off"
              />
            </label>
            <button type="submit">Connect</button>
          </form>
          <div className="toolbar">
            {Object.keys(THEMES).length > 1 && (
              <label className="appearance-setting" htmlFor="theme">
                Theme
                <select
                  id="theme"
                  value={themePreference.theme}
                  onChange={(event) => {
                    const theme = event.currentTarget.value as ThemeId;
                    setThemePreference((preference) => ({
                      ...preference,
                      theme,
                    }));
                  }}
                >
                  {Object.entries(THEMES).map(([id, definition]) => (
                    <option key={id} value={id}>
                      {definition.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="appearance-setting" htmlFor="appearance">
              Appearance
              <select
                id="appearance"
                value={themePreference.appearance}
                onChange={(event) => {
                  const appearance = event.currentTarget.value as Appearance;
                  setThemePreference((preference) => ({
                    ...preference,
                    appearance,
                  }));
                }}
              >
                <option value="system">Use system default</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </label>
            <label className="file-label">
              Open snapshot
              <input
                id="snapshot"
                type="file"
                accept="application/json,.json"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (file) {
                    clearToken();
                    setSelected(null);
                    setCargo(null);
                    void session.openSnapshot(file);
                  }
                }}
              />
            </label>
            <button
              type="button"
              id="export"
              disabled={!snapshot}
              onClick={session.exportSnapshot}
            >
              Export snapshot
            </button>
            <button
              type="button"
              id="refresh"
              disabled={!view.ready}
              onClick={session.refreshCurrent}
            >
              Refresh
            </button>
            <button
              type="button"
              id="disconnect"
              disabled={!view.connected}
              onClick={() => {
                clearToken();
                session.disconnect();
              }}
            >
              Disconnect
            </button>
          </div>
          <p className="hint">
            Inspect the full structured state. Gameplay controls are coming in
            the next delivery step. Tokens stay in page memory.
          </p>
        </section>
        <p id="error" role="alert" hidden={!view.error}>
          {view.error}
        </p>
        <section id="match" className="card" hidden={!snapshot}>
          <h2 id="match-title">
            {battle
              ? `Day ${battle.day} · ${owner(battle.active_player_slot)}'s turn`
              : "Match state"}
          </h2>
          <p id="boundary">
            {snapshot &&
              `${view.connected ? "Live match" : "Snapshot · read only"} · ${snapshot.summary.lifecycle} · Revision ${snapshot.summary.revision} · Frame ${obs?.game_state.frame ?? "unavailable"} · ${snapshot.summary.match_id}`}
          </p>
          <p id="readiness">
            {obs
              ? `Actions: ${obs.action_readiness} · ${obs.action_readiness_reasons.join("; ")}${battle ? ` · Weather: ${observed(battle.weather)} · Fog: ${observed(battle.fog_enabled)}` : ""}`
              : "No committed observation available."}
          </p>
          <p id="perspective">
            {snapshot && perspective(snapshot, view.identity, view.connected)} ·
            Active: {battle ? owner(battle.active_player_slot) : "Unknown"}
          </p>
          <div id="players">
            {battle?.players.map((player) => (
              <div
                key={player.slot}
                className={`player player-${player.slot}${player.slot === humanSlot(view.identity) ? " your-player" : ""}${player.slot === battle.active_player_slot ? " active-player" : ""}`}
              >
                <strong>
                  {owner(player.slot)} ·{" "}
                  {snapshot && playerName(snapshot, player.slot)}
                  {player.slot === humanSlot(view.identity) ? " · You" : ""}
                  {player.slot === battle.active_player_slot ? " · Active" : ""}
                </strong>
                <p>
                  Funds: {player.funds} · CO: {coName(player.co_id)} · ID{" "}
                  {player.co_id}
                </p>
                <p>
                  CO power:{" "}
                  {player.active_power === 0
                    ? "Inactive"
                    : `Active (observed flag ${player.active_power})`}
                </p>
                <p>Power meter: {observed(player.power_meter)}</p>
                <p>Charge thresholds unavailable; readiness is not inferred.</p>
                <p>
                  Units:{" "}
                  {
                    battle.units.filter((u) => u.army_slot === player.slot)
                      .length
                  }{" "}
                  · Properties:{" "}
                  {
                    battle.properties.filter(
                      (p) => p.owner_slot === player.slot,
                    ).length
                  }
                </p>
              </div>
            ))}
          </div>
        </section>
        <div className="workspace">
          <MapPanel
            battle={battle}
            selected={selected}
            select={select}
            empty={empty}
            yourSlot={humanSlot(view.identity)}
          />
          <aside className="card">
            <h2>Inspector</h2>
            <div id="inspector">
              {snapshot && battle && cargoUnit ? (
                <UnitInspector unit={cargoUnit} snapshot={snapshot} />
              ) : tile && snapshot ? (
                <>
                  <h3>
                    Tile ({tile.x}, {tile.y})
                  </h3>
                  <Details
                    entries={[
                      ["Terrain", terrainName(tile.terrain_class)],
                      ["Owner", owner(tile.owner_slot)],
                    ]}
                  />
                  {unit && (
                    <>
                      <UnitInspector unit={unit} snapshot={snapshot} />
                      {unit.cargo_references.map((ref) => {
                        const item = battle?.units.find(
                          (u) => u.reference === ref,
                        );
                        return item ? (
                          <UnitInspector
                            key={ref}
                            unit={item}
                            snapshot={snapshot}
                          />
                        ) : null;
                      })}
                    </>
                  )}
                </>
              ) : snapshot && !battle ? (
                "No battle data to inspect."
              ) : (
                "Select a tile or a unit."
              )}
            </div>
          </aside>
        </div>
        <section className="card">
          <h2>Unit roster</h2>
          <label>
            Filter units
            <input
              type="text"
              id="filter"
              placeholder="Type, player, coordinates…"
              value={filter}
              onChange={(event) => setFilter(event.currentTarget.value)}
            />
          </label>
          <div id="roster">
            {battle?.units.map((item) => {
              const text = `${unitName(item)} · ${owner(item.army_slot)} · (${item.x},${item.y}) · ${item.used_this_turn ? "Used" : "Ready"}${item.embarked ? " · Embarked" : ""}`;
              return text.toLowerCase().includes(filter.toLowerCase()) ? (
                <button
                  type="button"
                  key={item.reference}
                  onClick={() => {
                    if (item.embarked) setCargo(item.reference);
                    else {
                      select(item);
                      const button = document.querySelector<HTMLButtonElement>(
                        `#board button[data-x="${item.x}"][data-y="${item.y}"]`,
                      );
                      button?.focus();
                      button?.scrollIntoView({
                        block: "nearest",
                        inline: "nearest",
                      });
                    }
                  }}
                >
                  {text}
                </button>
              ) : null;
            })}
          </div>
        </section>
        <section className="card">
          <div className="toolbar">
            <h2>Emulator reference</h2>
            <button
              type="button"
              id="screenshot-button"
              disabled={!view.connected || !obs || !snapshot?.settled}
              onClick={session.loadScreenshot}
            >
              Load matching screenshot
            </button>
          </div>
          <p id="screenshot-label">{view.imageLabel}</p>
          <img
            id="screenshot"
            src={view.image ?? undefined}
            alt="Emulator screenshot for the displayed revision"
            hidden={!view.image}
          />
        </section>
      </main>
    </>
  );
}
