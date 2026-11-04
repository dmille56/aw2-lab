# Human game client proposal

Status: proposed; this document does not describe an implemented client.

## Purpose

Provide a local browser interface that turns the structured match state into a
readable, interactive board. A human should be able to understand the whole map,
inspect units and terrain, and play through the existing HTTP API while mGBA runs
headless. The same view should display a saved state document without a server.

This client supplies the human interface for Milestone 4 live verification.
It uses the existing authoritative match, commands, and revision tracking.

## First version

- Render the complete supported map with terrain, property ownership, and units.
- Show turn, day, player funds, weather, fog setting, lifecycle, and connection state.
- Show each player's CO power status and charge meter.
- Inspect any tile, property, or unit by selecting it.
- Play the existing purchase, move/wait, attack, capture, end-turn, and surrender actions.
- Follow committed state changes through HTTP SSE.
- Open an exported snapshot for inspection and export the current snapshot.
- Offer the original emulator screenshot as an optional reference for a matching revision.

Initially support the verified fixed Bean Island profile, including fog Off.
The interface must show unavailable or unknown observations explicitly. Future
fog support needs an explicit visibility contract before the client can promise
that its board respects player visibility.

## Screen layout

```text
 AW2 Lab     Bean Island       Day 3 · Orange's turn     Connected
 You: Orange · $12,000         Blue: $8,000              Revision 24
 -------------------------------------------------------------------
                             | Selected: Infantry · Orange
                             | Tile (4, 6): Plain
       Interactive map       | Health 100/100 · Ready
       with coordinates      | Fuel 96/99 · Ammo —
                             | Capture progress: none
       Terrain + ownership   |
       Units + health        | [Move] [Attack] [Capture]
       Selected path         | Destination/path preview
                             | [Confirm move and wait] [Cancel]
 -------------------------------------------------------------------
 Last action: Infantry moved (2,6) → (4,6) and waited · Completed
 [Activity] [Unit roster] [Screenshot] [Export snapshot]     [End turn]
```

The board takes most of the space. The inspector stays visible beside it on
desktop and moves below it on small screens. The full map fits initially;
zoom and pan support inspection without forcing the user to navigate an emulator
viewport. Board cells show their zero-based coordinates in the inspector, with
optional coordinate labels along the edges.

The default view emphasizes the player's turn, funds, unused units, and selected
unit. Revision and command details remain available in a secondary status area.
Errors use plain explanations with expandable server details.

## Board representation

Use an SVG board with original simple shapes and symbols. Terrain has distinct
colors and patterns: roads, rivers, woods, mountains, water, and properties remain
recognizable without game sprites. Property symbols and owner markings sit above
the terrain. A legend explains each terrain and unit symbol.

Units use a type symbol or abbreviation, owner color and label, and observed
health. Used units have an additional visible marker; selection and ownership
must remain distinguishable without relying on color. Embarked units appear in
their transport's inspector and roster rather than as independent map occupants
at their stored coordinates.

The first version shows internal health as observed, such as `100/100`, rather
than inventing an unverified HUD rounding rule. Unsupported numeric identifiers
appear as `Unknown unit (ID …)` or `Unknown terrain (ID …)` instead of silently
using a familiar icon.

Support mouse selection, keyboard cell navigation, Enter to inspect, and Escape
to cancel an action preview. Provide a searchable unit roster with links that
select and center each unit. The roster is also an alternative to navigating
the board visually.

## Inspection

Selecting a tile shows its coordinates, terrain, owner, and any occupying unit.
Selecting a unit adds its type, owner, lifetime identity, observed health, fuel,
ammo, turn status, capture points, and cargo. Static facts such as movement type,
movement allowance, weapon range, capacity, and purchase cost are labeled as rule
information, distinct from observed current values.

The player panel shows funds, CO identity where a verified name is available,
CO power status and charge meter, unit count, property count, and active turn.
Display the observed active power (none, CO Power, or Super CO Power when the
mapping is verified) and meter value for each player. Show normal and super power
thresholds and readiness when verified data supports them; a partial or unavailable
observation must not appear as an empty meter or an asserted ready state. Include
numeric meter information alongside the visual bar so status is readable without
color. These values update from the same committed revision as the board.
A match panel shows lifecycle,
weather, fog, readiness, and reasons why actions are blocked or unknown.

The inspector always describes the selected committed snapshot. A path preview
does not move the displayed unit until the command completes and a new state is
received.

## Human action flow

1. Select a ready owned unit. Choose Move, Attack, or Capture.
2. Build a path by selecting adjacent destination tiles; the starting tile is
   implicit. Show the arrows and destination, with undo and cancel controls.
3. Choose the final action. For attack, select an enemy target; an empty path
   permits a stationary attack. For capture, select the destination property.
4. Review a plain description, such as `Move Infantry to (4,6), then wait`, and
   confirm. The client submits the high-level action with the snapshot revision,
   lifetime unit identity, and a newly generated request ID.
5. Show the accepted command as pending. Follow its receipt until terminal,
   then render the resulting committed state and explain the outcome.

The client can check adjacency and obvious constraints using shared rule data.
Initial path selection is explicit; automatic route finding and full legal-move
enumeration are later work. Previews are labeled as estimates when rules or
observations are insufficient. The server decides whether the action is legal.
Direct units may move then attack; indirect units require a stationary attack.

Selecting an owned production property offers a purchase list with unit name,
cost, and remaining funds. End turn has a confirmation showing unused units.
Surrender uses a separate explicit confirmation. These controls become available
according to the caller's role, active slot, lifecycle, readiness, capabilities,
and command status.

Allow one pending mutation from this client at a time while preserving inspection.
If the displayed revision changes during a preview, invalidate that preview and
require review against the current state. A stale-revision response triggers a
state refresh and leaves the action unsubmitted. An uncertain transport outcome
retains the exact request ID and payload for receipt recovery or an identical
retry; a new click must not accidentally submit the same action twice.

## Connect and open snapshots

Serve the client from the API process at `/play`, using the same origin for HTTP
requests. The initial screen offers `Connect to match` and `Open snapshot`.

For a live connection, the human supplies the match ID and their player token.
Keep the token in page memory and send it only in the Authorization header.
Provide Disconnect, clear the view on authorization loss, and require reconnect
after a page reload. Do not put credentials in URLs, exported files, or browser
storage. Operator provisioning remains the existing trusted setup flow; this
first client joins a match that has already been provisioned.

For an imported document, accept the existing versioned state response and
validate its supported schema before rendering. Show `Snapshot · read only` with
its match, revision, and frame. A missing battle observation displays its reasons
instead of an empty map. Export the same coherent state envelope without tokens
or local paths. A snapshot can be inspected without live action controls.

## Data and synchronization

Use the existing state endpoint as the source for both the board and inspector.
It contains the summary and committed observation, including the map, roster,
unit identities, and readiness. Never combine panels from different revisions.

Use the existing authenticated HTTP event stream to learn that state or command
status changed, then fetch the authoritative document. Browser code consumes the
stream with `fetch` so it can supply the Authorization header. On reconnect or a
resynchronization signal, refresh state and pending command receipts. Display a
disconnected or resynchronizing status and disable submissions until refreshed.
Use SSE; no WebSocket transport is needed.

Request screenshots for an explicit committed revision. Display them with their
revision and frame; a missing matching screenshot is shown as unavailable rather
than substituted with a different boundary.

Generate a versioned presentation catalog from the existing Python unit profiles
and terrain names, delivered by the API to the client. This supplies readable
names and documented rule facts without maintaining a second rules table in
JavaScript. Movement calculations that become necessary beyond the initial path
editor should use shared authoritative rule services rather than a separate
browser implementation of the game.

## Implementation shape

Start with a small HTML/CSS/JavaScript application and SVG rendering, served as
packaged assets by FastAPI. This avoids a separate development server and build
toolchain for the initial interface. Keep rendering, selection/action previews,
and HTTP transport in separate modules.

The browser calls the HTTP API directly; it does not need the Python SDK or MCP
for ordinary play. MCP agents and the browser share the existing controller,
queue, authorization, revisions, journal, and emulator.

## Delivery steps and acceptance

1. Board and inspector: open exported state; render every tile and unit; select
   cells; show unavailable data and schema errors clearly. Verify against a
   committed live state and its screenshot.
2. Live viewer: player authentication, initial state, SSE updates, reconnect,
   roster, and revision-matched screenshot. Two clients must show the same
   committed revision and board after an action from either client.
3. Human controls: explicit path editor, purchase, move/wait, attack, capture,
   end turn, and surrender. Verify pending receipts, stale previews, uncertain
   responses, and permission loss without duplicate submissions.
4. Live acceptance: play the human side against an MCP host with the emulator
   headless, then windowed. Exercise the Milestone 4 action coverage and recovery
   requirements, and record evidence. Run all required repository checks.

Automatic routing, movement/attack range overlays, predicted damage, replay
timelines, new match setup, custom maps, and broader fog profiles are follow-up
features. The initial client needs a faithful inspectable board and reliable
existing actions to make the current human playtest practical.
