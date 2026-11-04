import { API_BASE } from "./transport.js";
import "./health.js";

const $ = (id) => document.getElementById(id);
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
};
let catalog = { terrain: {}, units: {} };
let snapshot = null;
let battle = null;
let selected = null;
let connection = null;
let imageURL = null;
let viewGeneration = 0;
const MATCH_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const owner = (slot) => (slot ? `Player ${slot}` : "Neutral");
const terrainName = (id) => catalog.terrain[id] ?? `Terrain ${id}`;
const unitName = (unit) =>
  catalog.units[unit.unit_type]?.name ?? `Unit ${unit.unit_type}`;
const observed = (value) =>
  value?.status === "available"
    ? String(value.value)
    : `${value?.status ?? "unavailable"}${value?.reasons?.length ? `: ${value.reasons.join("; ")}` : ""}`;
function error(message = "") {
  $("error").textContent = message;
  $("error").hidden = !message;
}
function clearImage() {
  if (imageURL) URL.revokeObjectURL(imageURL);
  imageURL = null;
  $("screenshot").hidden = true;
  $("screenshot").removeAttribute("src");
  $("screenshot-label").textContent =
    "Optional image from the displayed committed revision.";
}
function clearView() {
  snapshot = null;
  battle = null;
  selected = null;
  clearImage();
  for (const id of ["board", "players", "roster", "legend"])
    $(id).replaceChildren();
  $("match").hidden = true;
  $("empty").hidden = false;
  $("empty").textContent =
    "Connect or open an exported StateResponse JSON file to see the board.";
  $("inspector").textContent = "Select a tile or a unit.";
  $("export").disabled = true;
  $("screenshot-button").disabled = true;
}
function disconnect(message = "Disconnected") {
  viewGeneration += 1;
  connection?.abort.abort();
  connection = null;
  $("token").value = "";
  $("refresh").disabled = true;
  $("disconnect").disabled = true;
  $("connection").textContent = message;
  clearView();
}
function validateState(value) {
  const summary = value?.summary,
    observation = value?.observation;
  if (value?.contract_version !== 1 || summary?.contract_version !== 1)
    throw new Error("Unsupported API contract version; expected version 1.");
  if (
    !summary ||
    typeof summary.match_id !== "string" ||
    !MATCH_ID.test(summary.match_id) ||
    !Number.isSafeInteger(summary.revision) ||
    summary.revision < 0 ||
    typeof value.settled !== "boolean"
  )
    throw new Error(
      "Expected a versioned StateResponse with summary, settled, and observation.",
    );
  if (observation !== null) {
    if (
      observation?.schema_version !== 1 ||
      observation.game_state?.schema_version !== 4
    )
      throw new Error(
        "Unsupported observation schema. Expected match schema 1 and game-state schema 4.",
      );
    if (
      observation.match_id !== summary.match_id ||
      observation.revision !== summary.revision
    )
      throw new Error(
        "Snapshot summary and observation do not identify the same boundary.",
      );
    const data = observation.game_state.battle;
    if (!["available", "unavailable", "unknown"].includes(data?.status))
      throw new Error("Invalid battle observation.");
    if (data.status === "available") {
      const b = data.value,
        m = b?.map;
      if (
        !m ||
        !Number.isInteger(m.width) ||
        !Number.isInteger(m.height) ||
        m.width < 1 ||
        m.height < 1 ||
        m.width > 128 ||
        m.height > 128 ||
        !Array.isArray(m.tiles) ||
        m.tiles.length !== m.width * m.height ||
        !Array.isArray(b.units) ||
        b.units.length > 4096 ||
        !Array.isArray(b.players) ||
        b.players.length > 8
      )
        throw new Error("Invalid or oversized map, units, or players.");
      const seen = new Set();
      for (const tile of m.tiles) {
        if (
          !tile ||
          !Number.isInteger(tile.x) ||
          !Number.isInteger(tile.y) ||
          tile.x < 0 ||
          tile.y < 0 ||
          tile.x >= m.width ||
          tile.y >= m.height ||
          !Number.isInteger(tile.terrain_class) ||
          !Number.isInteger(tile.owner_slot)
        )
          throw new Error("Invalid map tile.");
        seen.add(`${tile.x},${tile.y}`);
      }
      if (seen.size !== m.tiles.length) throw new Error("Duplicate map tiles.");
      if (
        !b.units.every(
          (u) =>
            u &&
            Number.isInteger(u.reference) &&
            Number.isInteger(u.x) &&
            Number.isInteger(u.y) &&
            Number.isInteger(u.unit_type) &&
            Number.isInteger(u.army_slot),
        ) ||
        !b.players.every((p) => p && Number.isInteger(p.slot))
      )
        throw new Error("Invalid units or players.");
    }
  }
  return value;
}
function details(entries, parent) {
  const list = element("dl");
  for (const [key, value] of entries)
    list.append(element("dt", key), element("dd", value ?? "Unavailable"));
  parent.append(list);
}
function render(value) {
  snapshot = validateState(value);
  const obs = snapshot.observation;
  battle =
    obs?.game_state.battle.status === "available"
      ? obs.game_state.battle.value
      : null;
  clearImage();
  $("match").hidden = false;
  $("export").disabled = false;
  $("screenshot-button").disabled = !connection || !obs || !value.settled;
  $("match-title").textContent = battle
    ? `Day ${battle.day} · ${owner(battle.active_player_slot)}'s turn`
    : "Match state";
  $("boundary").textContent =
    `${connection ? "Live match" : "Snapshot · read only"} · ${value.summary.lifecycle} · Revision ${value.summary.revision} · Frame ${obs?.game_state.frame ?? "unavailable"} · ${value.summary.match_id}`;
  $("readiness").textContent = obs
    ? `Actions: ${obs.action_readiness} · ${(obs.action_readiness_reasons ?? []).join("; ")}${battle ? ` · Weather: ${observed(battle.weather)} · Fog: ${observed(battle.fog_enabled)}` : ""}`
    : "No committed observation available.";
  $("players").replaceChildren();
  $("board").replaceChildren();
  $("roster").replaceChildren();
  $("legend").replaceChildren();
  $("empty").hidden = !!battle;
  if (!battle) {
    $("empty").textContent = obs
      ? `Battle ${observed(obs.game_state.battle)}`
      : "No committed observation available.";
    $("inspector").textContent = "No battle data to inspect.";
    return;
  }
  for (const player of battle.players) {
    const panel = element("div", undefined, `player player-${player.slot}`);
    panel.append(
      element(
        "strong",
        `${owner(player.slot)}${player.slot === battle.active_player_slot ? " · Active" : ""}`,
      ),
    );
    panel.append(
      element("p", `Funds: ${player.funds} · CO ID: ${player.co_id}`),
    );
    panel.append(
      element(
        "p",
        `CO power: ${player.active_power === 0 ? "Inactive" : `Active (observed flag ${player.active_power})`}`,
      ),
    );
    panel.append(element("p", `Power meter: ${observed(player.power_meter)}`));
    panel.append(
      element("p", "Charge thresholds unavailable; readiness is not inferred."),
    );
    panel.append(
      element(
        "p",
        `Units: ${battle.units.filter((u) => u.army_slot === player.slot).length} · Properties: ${(battle.properties ?? []).filter((p) => p.owner_slot === player.slot).length}`,
      ),
    );
    $("players").append(panel);
  }
  $("board").style.gridTemplateColumns =
    `repeat(${battle.map.width}, var(--cell))`;
  const occupancy = new Map(
    battle.units.filter((u) => !u.embarked).map((u) => [`${u.x},${u.y}`, u]),
  );
  const tiles = [...battle.map.tiles].sort((a, b) => a.y - b.y || a.x - b.x);
  for (const tile of tiles) {
    const unit = occupancy.get(`${tile.x},${tile.y}`);
    const button = element(
      "button",
      undefined,
      `tile terrain-${tile.terrain_class} owner-${unit?.army_slot ?? tile.owner_slot}`,
    );
    button.type = "button";
    button.dataset.x = tile.x;
    button.dataset.y = tile.y;
    button.setAttribute(
      "aria-label",
      `(${tile.x}, ${tile.y}) ${terrainName(tile.terrain_class)}, ${owner(tile.owner_slot)}${unit ? `, ${unitName(unit)}, ${owner(unit.army_slot)}, health ${unit.internal_health}, ${unit.used_this_turn ? "used" : "ready"}` : ""}`,
    );
    button.append(
      element("span", `P${tile.owner_slot || "–"}`, "owner-tag"),
      element("span", terrainName(tile.terrain_class)),
    );
    if (unit) {
      button.append(
        element("span", unitName(unit), "unit"),
        element(
          "span",
          `${unit.internal_health}/100${unit.used_this_turn ? " ✓" : ""}`,
        ),
      );
    }
    button.append(element("span", `${tile.x},${tile.y}`, "coords"));
    button.addEventListener("click", () => select(tile.x, tile.y));
    button.addEventListener("keydown", (event) => {
      const delta = {
        ArrowLeft: [-1, 0],
        ArrowRight: [1, 0],
        ArrowUp: [0, -1],
        ArrowDown: [0, 1],
      }[event.key];
      if (!delta) return;
      event.preventDefault();
      select(
        Math.max(0, Math.min(battle.map.width - 1, tile.x + delta[0])),
        Math.max(0, Math.min(battle.map.height - 1, tile.y + delta[1])),
        true,
      );
    });
    $("board").append(button);
  }
  for (const id of [...new Set(tiles.map((t) => t.terrain_class))].sort(
    (a, b) => a - b,
  ))
    $("legend").append(element("span", terrainName(id)));
  renderRoster();
  if (selected && tiles.some((t) => t.x === selected.x && t.y === selected.y))
    select(selected.x, selected.y);
  else {
    selected = null;
    $("inspector").textContent = "Select a tile or a unit.";
  }
}
function inspectUnit(unit, panel) {
  const profile = catalog.units[unit.unit_type];
  panel.append(element("h3", `${unitName(unit)} · ${owner(unit.army_slot)}`));
  const identity = snapshot.observation.unit_identities?.find(
    (id) => id.reference === unit.reference,
  );
  details(
    [
      ["Health (internal)", `${unit.internal_health}/100`],
      ["Turn status", unit.used_this_turn ? "Used" : "Ready"],
      ["Fuel", `${unit.fuel}${profile ? `/${profile.fuel_capacity}` : ""}`],
      ["Ammo", `${unit.ammo}${profile ? `/${profile.ammo_capacity}` : ""}`],
      ["Capture points (observed)", unit.capture_points],
      ["Embarked", unit.embarked ? "Yes" : "No"],
      ["Unit identity", identity?.identity_id ?? "Unavailable"],
      ["Cargo references", (unit.cargo_references ?? []).join(", ") || "None"],
    ],
    panel,
  );
  if (profile) {
    panel.append(element("h3", "Baseline rule information"));
    details(
      [
        ["Movement", `${profile.movement} · ${profile.movement_type}`],
        ["Weapon range", `${profile.minimum_range}–${profile.maximum_range}`],
        ["Cost", profile.cost],
      ],
      panel,
    );
    panel.append(
      element("p", "Current CO effects may change baseline rules.", "hint"),
    );
  }
}
function select(x, y, focus = false) {
  if (!battle) return;
  selected = { x, y };
  const tile = battle.map.tiles.find((t) => t.x === x && t.y === y);
  const panel = $("inspector");
  panel.replaceChildren(element("h3", `Tile (${x}, ${y})`));
  details(
    [
      ["Terrain", terrainName(tile.terrain_class)],
      ["Owner", owner(tile.owner_slot)],
    ],
    panel,
  );
  const unit = battle.units.find((u) => u.x === x && u.y === y && !u.embarked);
  if (unit) {
    inspectUnit(unit, panel);
    for (const ref of unit.cargo_references ?? []) {
      const cargo = battle.units.find((u) => u.reference === ref);
      if (cargo) inspectUnit(cargo, panel);
    }
  }
  for (const button of $("board").children) {
    const match =
      Number(button.dataset.x) === x && Number(button.dataset.y) === y;
    button.classList.toggle("selected", match);
    button.setAttribute("aria-pressed", String(match));
    if (match && focus) {
      button.focus();
      button.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }
}
function renderRoster() {
  $("roster").replaceChildren();
  if (!battle) return;
  const query = $("filter").value.toLowerCase();
  for (const unit of battle.units) {
    const text = `${unitName(unit)} · ${owner(unit.army_slot)} · (${unit.x},${unit.y}) · ${unit.used_this_turn ? "Used" : "Ready"}${unit.embarked ? " · Embarked" : ""}`;
    if (!text.toLowerCase().includes(query)) continue;
    const button = element("button", text);
    button.onclick = () => {
      if (!unit.embarked) select(unit.x, unit.y, true);
      else {
        $("inspector").replaceChildren();
        inspectUnit(unit, $("inspector"));
      }
    };
    $("roster").append(button);
  }
}
async function request(c, suffix) {
  const response = await fetch(`${API_BASE}/v1/matches/${c.id}/${suffix}`, {
    headers: { Authorization: `Bearer ${c.token}` },
    signal: c.abort.signal,
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (response.status === 401 || response.status === 403) {
    if (connection === c) disconnect("Authorization lost · reconnect required");
    throw new Error("This credential no longer has access to the match.");
  }
  if (!response.ok)
    throw new Error(
      `Request failed (${response.status}). Check match access and server status.`,
    );
  return response;
}
async function refresh(c) {
  // Serialize refreshes; an event during a fetch schedules one more authoritative read.
  c.again = true;
  if (c.refreshing) return c.refreshing;
  c.refreshing = (async () => {
    while (c.again && connection === c) {
      c.again = false;
      const value = validateState(await (await request(c, "state")).json());
      if (value.summary.match_id !== c.id)
        throw new Error("Server returned a different match.");
      if (
        connection === c &&
        (!snapshot || value.summary.revision >= snapshot.summary.revision)
      )
        render(value);
    }
  })();
  try {
    await c.refreshing;
  } finally {
    c.refreshing = null;
  }
}
async function follow(c) {
  let delay = 1000;
  while (connection === c) {
    try {
      const response = await request(c, "events");
      if (!response.body) throw new Error("Event stream unavailable");
      const reader = response.body
        .pipeThrough(new TextDecoderStream())
        .getReader();
      let buffer = "";
      try {
        await refresh(c);
        if (connection !== c) return;
        $("connection").textContent =
          "Live · observing committed match updates";
        delay = 1000;
        while (connection === c) {
          const { value, done } = await reader.read();
          if (done) throw new Error("Event stream disconnected");
          buffer += value;
          if (buffer.length > 1048576)
            throw new Error("Event stream exceeded client limit");
          let end;
          while ((end = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            if (frame.split("\n").some((line) => line.startsWith("data:")))
              await refresh(c);
          }
        }
      } finally {
        await reader.cancel().catch(() => {});
      }
    } catch (e) {
      if (connection !== c || c.abort.signal.aborted) return;
      $("connection").textContent =
        `Disconnected · retrying in ${delay / 1000}s`;
      await new Promise((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          c.abort.signal.removeEventListener("abort", finish);
          resolve();
        };
        const timer = setTimeout(finish, delay);
        c.abort.signal.addEventListener("abort", finish, { once: true });
      });
      delay = Math.min(delay * 2, 15000);
    }
  }
}
$("connect").onsubmit = async (event) => {
  event.preventDefault();
  const id = $("match-id").value.trim().toLowerCase(),
    token = $("token").value;
  disconnect("Connecting…");
  error();
  if (!MATCH_ID.test(id)) {
    error("Enter a valid match UUID.");
    return;
  }
  const c = {
    id,
    token,
    abort: new AbortController(),
    refreshing: null,
    again: false,
  };
  connection = c;
  $("disconnect").disabled = false;
  try {
    await refresh(c);
    if (connection !== c) return;
    $("refresh").disabled = false;
    void follow(c);
  } catch (e) {
    if (connection === c) disconnect("Connection failed");
    if (e.name !== "AbortError") error(e.message);
  }
};
$("disconnect").onclick = () => {
  disconnect();
  error();
};
$("refresh").onclick = async () => {
  const c = connection;
  if (c)
    try {
      await refresh(c);
      error();
    } catch (e) {
      if (e.name !== "AbortError") error(e.message);
    }
};
$("snapshot").onchange = async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  disconnect("Opening snapshot…");
  error();
  const generation = viewGeneration;
  try {
    if (file.size > 5 * 1024 * 1024)
      throw new Error("Snapshot exceeds the 5 MiB limit.");
    const value = validateState(JSON.parse(await file.text()));
    if (generation !== viewGeneration) return;
    render(value);
    $("connection").textContent = "Snapshot · read only";
  } catch (e) {
    if (generation === viewGeneration) {
      clearView();
      $("connection").textContent = "Snapshot could not be opened";
      error(e.message);
    }
  }
};
$("export").onclick = () => {
  if (!snapshot) return;
  // Explicitly select the public envelope; connection credentials are never included.
  const output = {
    contract_version: snapshot.contract_version,
    summary: snapshot.summary,
    settled: snapshot.settled,
    observation: snapshot.observation,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(output, null, 2)], { type: "application/json" }),
  );
  const a = element("a");
  a.href = url;
  a.download = `aw2-${snapshot.summary.match_id}-revision-${snapshot.summary.revision}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$("screenshot-button").onclick = async () => {
  const c = connection,
    revision = snapshot?.summary.revision,
    frame = snapshot?.observation?.game_state.frame;
  if (!c || revision === undefined) return;
  try {
    const response = await request(c, `screenshot?revision=${revision}`);
    if (!response.headers.get("content-type")?.startsWith("image/png"))
      throw new Error("Server did not return a PNG screenshot.");
    if (
      response.headers.get("X-AW2-Match-ID") !== c.id ||
      response.headers.get("X-AW2-Revision") !== String(revision) ||
      response.headers.get("X-AW2-Frame") !== String(frame)
    )
      throw new Error(
        "Screenshot metadata does not match the displayed boundary.",
      );
    const blob = await response.blob();
    if (blob.size > 1024 * 1024 || blob.size < 8)
      throw new Error("Screenshot has an invalid size.");
    const signature = new Uint8Array(await blob.slice(0, 8).arrayBuffer());
    if (
      ![137, 80, 78, 71, 13, 10, 26, 10].every(
        (byte, i) => signature[i] === byte,
      )
    )
      throw new Error("Screenshot is not a PNG image.");
    if (connection !== c || snapshot?.summary.revision !== revision) return;
    clearImage();
    imageURL = URL.createObjectURL(blob);
    $("screenshot").src = imageURL;
    $("screenshot").hidden = false;
    $("screenshot-label").textContent =
      `Revision ${revision} · Frame ${snapshot.observation.game_state.frame}`;
    error();
  } catch (e) {
    if (e.name !== "AbortError") error(e.message);
  }
};
$("filter").oninput = renderRoster;
$("zoom").oninput = () =>
  document.documentElement.style.setProperty("--cell", `${$("zoom").value}px`);
try {
  const response = await fetch(new URL("./catalog.json", import.meta.url), {
    credentials: "omit",
  });
  if (!response.ok) throw new Error("catalog");
  catalog = await response.json();
  if (catalog.schema_version !== 1) throw new Error("catalog schema");
  if (snapshot) render(snapshot);
} catch {
  error(
    "Presentation catalog unavailable. Numeric unit and terrain identifiers will be shown.",
  );
}
