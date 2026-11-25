import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
  type CSSProperties,
} from "react";
import { claimLocalLaunch } from "./launch_handoff";
import { TerrainDefense } from "./TerrainDefense";
import { MapPanel } from "./MapPanel";
import {
  CAPTURE_POINTS_REQUIRED,
  coName,
  humanSlot,
  perspective,
  playerName,
  propertyCapturePoints,
} from "./presentation";
import { Health } from "./Health";
import { MatchSession } from "./session";
import { PlayerHud } from "./PlayerHud";
import { MatchControls, PurchaseMenu } from "./MatchControls";
import { ContextActions, restoreBoardFocus } from "./ContextActions";
import { GameNotifications } from "./GameNotifications";
import { ActionProgress } from "./ActionProgress";
import { CommandFeedback } from "./CommandFeedback";
import { CommandPanel } from "./CommandPanel";
import { useGameplay } from "./gameplay";
import {
  activePowerLabel,
  nextPowerThresholdLabel,
  powerMeterLabel,
} from "./co_power";
import {
  applyTheme,
  readThemePreference,
  saveThemePreference,
  THEMES,
  type Appearance,
  type ThemeId,
} from "./appearance";
import {
  applyUiScale,
  readUiScale,
  saveUiScale,
  UI_SCALE_DEFAULT,
  UI_SCALE_MAX,
  UI_SCALE_MIN,
  UI_SCALE_STEP,
} from "./ui_scale";
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
  const [launchError, setLaunchError] = useState("");
  const launch = useRef<ReturnType<typeof claimLocalLaunch> | null>(null);
  useEffect(() => {
    let active = true;
    const claim = () => {
      if (new URLSearchParams(window.location.hash.slice(1)).has("launch"))
        launch.current = claimLocalLaunch();
      else launch.current ??= claimLocalLaunch();
      const pending = launch.current;
      void pending
        .then((handoff) => {
          if (active && launch.current === pending && handoff) {
            setLaunchError("");
            void session.connect(handoff.match_id, handoff.token);
          }
        })
        .catch(() => {
          if (active && launch.current === pending)
            setLaunchError(
              "Local launch failed or link expired. Connect manually or use a new launch link.",
            );
        });
    };
    claim();
    window.addEventListener("hashchange", claim);
    return () => {
      active = false;
      window.removeEventListener("hashchange", claim);
    };
  }, [session]);
  const [selected, setSelected] = useState<Position | null>(null);
  const [cargo, setCargo] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [boardWidth, setBoardWidth] = useState<number | null>(null);
  const [themePreference, setThemePreference] = useState(readThemePreference);
  const [uiScale, setUiScale] = useState(readUiScale);
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
  useEffect(() => {
    applyUiScale(document.documentElement, uiScale);
    saveUiScale(uiScale);
  }, [uiScale]);
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
  const property = battle?.properties.find(
    (item) => item.x === tile?.x && item.y === tile.y,
  );
  const capturePoints = propertyCapturePoints(unit, property);
  const select = (position: Position) => {
    setSelected(position);
    setCargo(null);
  };
  const gameplay = useGameplay(view, select, {
    automaticRouting: true,
    onCommit: (action, revision) => {
      void session.submitAction(action, revision);
    },
  });
  const finished = snapshot?.summary.lifecycle === "finished";
  const yourSlot = humanSlot(view.identity);
  const outcome =
    finished && view.connected && yourSlot !== null
      ? obs?.game_state.versus_result?.find(
          (result) => result.slot === `slot_${yourSlot}`,
        )?.outcome
      : undefined;
  const showBoardRecovery =
    view.connected && !!snapshot && !finished && !!gameplay.unavailable;
  const boardRecoveryError = showBoardRecovery && !view.ready ? view.error : "";
  const recoverSession = () => {
    gameplay.reset("Action plan cleared for session recovery.");
    void session.recoverCurrent();
  };
  const cancelBoardAction = gameplay.pending
    ? undefined
    : () => {
        gameplay.cancel();
        restoreBoardFocus(gameplay.draft.origin);
      };
  const empty = !snapshot
    ? "Connect or open an exported StateResponse JSON file to see the board."
    : obs
      ? `Battle ${observed(obs.game_state.battle)}`
      : "No committed observation available.";
  return (
    <>
      <a className="skip-link" href="#draft-heading">
        Skip to gameplay actions
      </a>
      <GameNotifications view={view} onRefresh={session.refreshCurrent} />
      <header>
        <div>
          <span className="eyebrow">AW2 LAB</span>
          <h1>Match workspace</h1>
        </div>
        <div className="session-controls">
          <p id="connection" role="status">
            {view.status}
          </p>
          <div className="toolbar">
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
            {view.connected && snapshot && !showBoardRecovery && (
              <button
                type="button"
                title="Reconnect and clear the current action plan"
                onClick={recoverSession}
              >
                Recover session
              </button>
            )}
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
        </div>
      </header>
      <main>
        <details className="card client-settings" open={!snapshot}>
          <summary>Connection, display, and snapshots</summary>
          <section className="setup" aria-label="Open match">
            <details className="connection-settings" open={!view.connected}>
              <summary>Connect to a match</summary>
              <Health />
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
                  setLaunchError("");
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
            </details>
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
              <fieldset className="ui-scale-setting">
                <legend>Interface scale (50–200%)</legend>
                <div>
                  <button
                    type="button"
                    id="ui-scale-decrease"
                    aria-label="Decrease interface scale"
                    disabled={uiScale <= UI_SCALE_MIN}
                    onClick={() =>
                      setUiScale((scale) =>
                        Math.max(UI_SCALE_MIN, scale - UI_SCALE_STEP),
                      )
                    }
                  >
                    −
                  </button>
                  <output id="ui-scale-value" aria-live="polite">
                    {uiScale}%
                  </output>
                  <button
                    type="button"
                    id="ui-scale-increase"
                    aria-label="Increase interface scale"
                    disabled={uiScale >= UI_SCALE_MAX}
                    onClick={() =>
                      setUiScale((scale) =>
                        Math.min(UI_SCALE_MAX, scale + UI_SCALE_STEP),
                      )
                    }
                  >
                    +
                  </button>
                  <button
                    type="button"
                    id="ui-scale-reset"
                    disabled={uiScale === UI_SCALE_DEFAULT}
                    onClick={() => setUiScale(UI_SCALE_DEFAULT)}
                  >
                    Reset
                  </button>
                </div>
              </fieldset>
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
                      setLaunchError("");
                      setSelected(null);
                      setCargo(null);
                      void session.openSnapshot(file);
                    }
                  }}
                />
              </label>
            </div>
            <p className="hint">
              Inspect the full structured state. Tokens stay in page memory.
            </p>
          </section>
        </details>
        <p
          id="error"
          role="alert"
          hidden={(!view.error || !!boardRecoveryError) && !launchError}
        >
          {(boardRecoveryError ? "" : view.error) || launchError}
        </p>
        <div
          className="workspace"
          id="workspace"
          style={
            {
              "--board-width":
                boardWidth === null ? undefined : `${boardWidth}px`,
            } as CSSProperties
          }
        >
          <div className="gameplay-sidebar">
            <section id="match" className="card" hidden={!snapshot}>
              <h2 id="match-title">
                {snapshot
                  ? snapshot.summary.configuration.map_id.replaceAll("_", " ")
                  : "Match overview"}
              </h2>
              {battle && (
                <p className="turn-summary" aria-label="Current turn">
                  Day {battle.day} · {owner(battle.active_player_slot)}’s turn
                  {battle.active_player_slot === humanSlot(view.identity)
                    ? " · Your turn"
                    : ""}
                  {" · "}Funds:{" "}
                  {battle.players.find(
                    (player) => player.slot === battle.active_player_slot,
                  )?.funds ?? "Unavailable"}
                </p>
              )}
              {battle && (
                <PlayerHud
                  battle={battle}
                  yourSlot={humanSlot(view.identity)}
                />
              )}
              <MatchControls
                model={gameplay}
                view={view}
                onSubmit={session.submitAction}
              />
              <p id="perspective">
                {snapshot &&
                  perspective(snapshot, view.identity, view.connected)}
              </p>
              <details className="match-details">
                <summary>Match details and player statistics</summary>
                <p id="boundary">
                  {snapshot &&
                    `${view.connected ? "Live match" : "Snapshot · read only"} · Revision ${snapshot.summary.revision} · Frame ${obs?.game_state.frame ?? "unavailable"} · ${snapshot.summary.match_id}`}
                </p>

                <Details
                  entries={[
                    ["Lifecycle", snapshot?.summary.lifecycle ?? "Unavailable"],
                    [
                      "Day",
                      battle
                        ? battle.day
                        : "Unavailable (battle state not observed)",
                    ],
                    [
                      "Active player",
                      battle
                        ? owner(battle.active_player_slot)
                        : "Unavailable (battle state not observed)",
                    ],
                    [
                      "Weather",
                      battle
                        ? observed(battle.weather)
                        : observed(obs?.game_state.battle),
                    ],
                    [
                      "Fog",
                      battle
                        ? observed(battle.fog_enabled)
                        : observed(obs?.game_state.battle),
                    ],
                    [
                      "Action readiness",
                      obs
                        ? `${obs.action_readiness}${obs.action_readiness_reasons.length ? ` · ${obs.action_readiness_reasons.join("; ")}` : ""}`
                        : "Unavailable (no committed observation)",
                    ],
                  ]}
                />
                <div id="players">
                  {battle?.players.map((player) => (
                    <div
                      key={player.slot}
                      className={`player player-${player.slot}${player.slot === humanSlot(view.identity) ? " your-player" : ""}${player.slot === battle.active_player_slot ? " active-player" : ""}`}
                    >
                      <strong>
                        {owner(player.slot)} ·{" "}
                        {snapshot && playerName(snapshot, player.slot)}
                        {player.slot === humanSlot(view.identity)
                          ? " · You"
                          : ""}
                        {player.slot === battle.active_player_slot
                          ? " · Active"
                          : ""}
                      </strong>
                      <p>
                        Funds: {player.funds} · CO: {coName(player.co_id)} · ID{" "}
                        {player.co_id}
                      </p>
                      <p>CO power: {activePowerLabel(player.active_power)}</p>
                      <p>Power meter: {powerMeterLabel(player.power_meter)}</p>
                      <p>Power uses: {observed(player.power_use_counter)}</p>
                      <p>
                        Charge thresholds:{" "}
                        {nextPowerThresholdLabel(
                          player.co_id,
                          player.power_use_counter,
                        )}
                      </p>
                      <p>
                        Units:{" "}
                        {
                          battle.units.filter(
                            (u) => u.army_slot === player.slot,
                          ).length
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
              </details>
            </section>

            {gameplay.selectedUnit &&
              gameplay.draft.routeMode === "automatic" &&
              gameplay.draft.phase === "unit" && (
                <button
                  type="button"
                  disabled={!gameplay.editable}
                  onClick={() => {
                    gameplay.dispatch({ type: "plan" });
                    const point = gameplay.draft.origin;
                    if (point)
                      document
                        .querySelector<HTMLButtonElement>(
                          `#board button[data-x="${point.x}"][data-y="${point.y}"]`,
                        )
                        ?.focus();
                  }}
                >
                  Plan movement
                </button>
              )}
            <CommandPanel model={gameplay} />
            <aside className="card">
              <h2>Inspector</h2>
              <div id="inspector">
                {snapshot && battle && cargoUnit ? (
                  <UnitInspector
                    unit={cargoUnit}
                    snapshot={snapshot}
                    viewerSlot={humanSlot(view.identity)}
                  />
                ) : tile && snapshot ? (
                  <>
                    <h3>
                      Tile ({tile.x}, {tile.y})
                    </h3>
                    <Details
                      entries={[
                        ["Terrain", terrainName(tile.terrain_class)],
                        ["Owner", owner(tile.owner_slot)],
                        ...(capturePoints !== null
                          ? [
                              [
                                "Capture progress",
                                <>
                                  {CAPTURE_POINTS_REQUIRED - capturePoints}{" "}
                                  points remaining
                                  <progress
                                    aria-label="Capture progress"
                                    className="property-capture-progress"
                                    max={CAPTURE_POINTS_REQUIRED}
                                    value={capturePoints}
                                  />
                                </>,
                              ] as [string, ReactNode],
                            ]
                          : []),
                        ...(!unit
                          ? [
                              [
                                "Tile defense",
                                <TerrainDefense
                                  terrainClass={tile.terrain_class}
                                />,
                              ] as [string, ReactNode],
                            ]
                          : []),
                      ]}
                    />
                    {unit && (
                      <>
                        <UnitInspector
                          unit={unit}
                          snapshot={snapshot}
                          viewerSlot={humanSlot(view.identity)}
                        />
                        {unit.cargo_references.map((ref) => {
                          const item = battle?.units.find(
                            (u) => u.reference === ref,
                          );
                          return item ? (
                            <UnitInspector
                              key={ref}
                              unit={item}
                              snapshot={snapshot}
                              viewerSlot={humanSlot(view.identity)}
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

          <div className="board-column">
            <ActionProgress view={view} />
            {showBoardRecovery && (
              <section className="card" aria-label="Gameplay recovery">
                <p role="status">{gameplay.unavailable}</p>
                {boardRecoveryError && <p role="alert">{boardRecoveryError}</p>}
                <button type="button" onClick={recoverSession}>
                  Recover session
                </button>
              </section>
            )}
            <MapPanel
              onBoardWidthChange={setBoardWidth}
              turnMode={
                view.connected ? "live" : snapshot ? "snapshot" : "unavailable"
              }
              finished={finished}
              outcome={outcome}
              battle={battle}
              selected={selected}
              select={gameplay.inspectTile}
              activate={gameplay.activate}
              cancel={cancelBoardAction}
              cancelAttackTarget={
                gameplay.draft.contextual &&
                gameplay.draft.phase === "target" &&
                (gameplay.draft.kind === "attack" ||
                  gameplay.draft.kind === "move_attack")
                  ? cancelBoardAction
                  : undefined
              }
              route={
                gameplay.draft.boundary === gameplay.boundary &&
                gameplay.draft.origin &&
                gameplay.draft.phase !== "unit"
                  ? [gameplay.draft.origin, ...gameplay.draft.path]
                  : []
              }
              target={
                gameplay.draft.boundary === gameplay.boundary
                  ? gameplay.draft.target
                  : null
              }
              dropTargets={
                gameplay.draft.boundary === gameplay.boundary &&
                gameplay.draft.phase === "review" &&
                gameplay.draft.kind === "unload"
                  ? gameplay.unloadTargets
                  : new Set<string>()
              }
              selectedUnit={
                gameplay.draft.boundary === gameplay.boundary
                  ? gameplay.selectedUnit
                  : null
              }
              selectedUnitKey={
                gameplay.draft.boundary === gameplay.boundary &&
                gameplay.selectedUnit
                  ? gameplay.draft.unitId
                  : null
              }
              plannedRoute={
                gameplay.draft.boundary === gameplay.boundary &&
                gameplay.draft.phase !== "unit"
                  ? gameplay.draft.path
                  : []
              }
              enemyTargets={
                new Set(
                  gameplay.attackableTargets.map(
                    (unit) => `${unit.x},${unit.y}`,
                  ),
                )
              }
              actionTargets={
                gameplay.draft.contextual && gameplay.draft.phase === "target"
                  ? new Set(
                      gameplay.draft.kind === "silo_launch"
                        ? []
                        : gameplay.targets.map((unit) => `${unit.x},${unit.y}`),
                    )
                  : undefined
              }
              dropSelections={Object.fromEntries(
                gameplay.selectedTransportCargo.flatMap(({ id }, index) => {
                  const point = gameplay.draft.dropDestinations[id];
                  return point
                    ? [[`${point.x},${point.y}`, `D${index + 1}`]]
                    : [];
                }),
              )}
              empty={empty}
              yourSlot={yourSlot}
            />
            <CommandFeedback
              view={view}
              onRetry={session.retryUncertainAction}
              onCheckStatus={session.checkCommandStatus}
            />
          </div>
          <PurchaseMenu
            model={gameplay}
            view={view}
            onSubmit={session.submitAction}
          />
          <ContextActions
            model={gameplay}
            view={view}
            onSubmit={session.submitAction}
          />
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
                      gameplay.inspectTile(item);
                      gameplay.selectUnit(
                        obs?.unit_identities.find(
                          (identity) => identity.reference === item.reference,
                        )?.identity_id ?? "",
                      );
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
