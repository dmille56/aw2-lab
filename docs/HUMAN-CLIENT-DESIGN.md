# Human game client proposal

Status: the React/TypeScript viewer and supported gameplay controls are
implemented in `prototypes/client/`. Remaining acceptance and follow-up features
are tracked in [Milestone 4](MILESTONE-4.org).

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

### Initial implementation evidence

The existing [browser/Tauri prototype](../prototypes/client/README.md) now serves
the viewer at `/client/`. No separate frontend is installed in the Python package.
The board now uses compact labels, responsive fit sizing, and optional coordinates.
Authenticated caller identity distinguishes your slot from the active player; player
names come from match metadata and numeric CO names are limited to verified mappings.
Snapshots and unavailable names remain explicit.
The viewer now uses React and TypeScript with Vite; browser and Tauri share its
production assets. Local gates cover strict typing, generated contracts, component
tests, production browser scenarios, and packaged native health smoke checks.

On 2026-11-04, Chromium browser checks covered authenticated state loading,
tile and unit inspection, keyboard selection, roster filtering, versioned snapshot
import/export, rejection of unsupported schemas, SSE state changes, removal of
stale screenshots, and clearing state on authorization loss. Change and revocation
checks used synthetic observations. The downloaded snapshot also passed the
Python `StateResponse` validator.

Against the real headless emulator and an isolated recovered Bean Island match,
the browser rendered all 240 tiles and the Infantry inspector, and loaded a
screenshot matching committed revision 4/frame 4270. This verifies observation
delivery and rendering, not gameplay controls or a completed human/agent match.

The Nix Tauri package built successfully. Its existing X11 native smoke check
reached the real API and reported the running emulator, then exited zero. It
emitted GBM buffer warnings, as the earlier prototype did. Native gameplay
rendering, native snapshot file handling, and Wayland acceptance for this viewer
remain unverified. CO charge is currently shown numerically; verified thresholds
and a visual charge meter remain pending.

`tests/test_client_prototype.py` covers helper configuration, shared asset delivery,
native Authorization preflight policy, unrelated-origin rejection, and catalog drift.

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

Extend the existing client in `prototypes/client/`, sharing its browser assets
and Tauri shell. Serve it through the existing helper at `/client/`, using the
same origin for browser HTTP requests and the configured loopback destination
for the native shell. The initial screen offers `Connect to match` and `Open snapshot`.

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

Generate and bundle a versioned presentation catalog from the existing Python unit profiles
and terrain names. Check that the bundled catalog matches the generator in the
test suite. This keeps snapshots readable without an API connection and supplies readable
names and documented rule facts without maintaining a second rules table in
JavaScript. Movement calculations that become necessary beyond the initial path
editor should use shared authoritative rule services rather than a separate
browser implementation of the game.

## Implementation shape

The existing prototype provides a React/TypeScript board, inspector, and
supported gameplay actions with accessible selectable tiles. Retain its
connection check, native smoke reporting, and shared browser/Tauri assets. Do
not create a second frontend in the Python package. React/TypeScript/Vite tooling
and generated contract types follow [the accepted client architecture](CLIENT-ARCHITECTURE.md).
Keep rendering, selection/action previews, activity, and HTTP transport in
separate modules as it grows.

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


## Usability redesign: first pass (2026-11-15)

Code inspection identified two sources of friction before reaching the board:
the connection form stays prominent during play, and full match/player statistics
occupy vertical space above gameplay. This is an initial inspection finding;
human playtesting has not yet established the highest-friction interactions.

The first pass collapses the connection form after a live connection while
keeping reconnect access in a labeled disclosure. Refresh, export, and disconnect
stay available outside it. A compact day, active-player, funds, and your-turn
summary stays visible alongside the connection perspective. Detailed match
observations and player power statistics move into an expandable section.
A keyboard skip link reaches gameplay actions directly. Existing action previews,
confirmation, cancellation, board controls, and inspector behavior are retained.

Next, playtest connecting, selecting and moving a unit, attacking, purchasing,
unloading, canceling a draft, ending a turn, and recovering from an error. Record
where players hesitate or lose board context across keyboard, mouse, and touch.
Use those findings to guide the next layout pass and check narrow windows and
accessibility before beginning platform acceptance. Automated disclosure checks
use synthetic match state and do not establish live human usability.


## Advance Wars client redesign

Kickoff: 2026-11-15. The ordered implementation and acceptance checklist is in
[Milestone 4](MILESTONE-4.org). Each item is implemented, reviewed, and committed
separately. The preceding layout pass is the starting point for this redesign.

### Agreed presentation and artwork

Use an AWBW-style play area with a large sprite board, compact day/player/funds/CO
HUD, concise unit/terrain inspection, and contextual actions. Use actual static
sprites extracted from the checksum-verified local US revision-0 ROM. Prove the
extraction on representative terrain/property/ground/air/naval samples before
building complete atlases. Record verified offsets, palettes, transparency, and
reproducible decoding rules. Store generated files in an external user cache,
outside Git and the Nix store; serve only the manifest and images, never the ROM.
Use representative terrain tiles; defer animation, exact terrain connections,
weather palettes, and CO portraits. Keep symbolic rendering with a setup message
when the sprite pack is absent. Retain accessible tile names and keyboard
navigation. Display HP as ceil(internal health / 10), with exact health available
in expanded inspection; mark used units and ownership without color alone.

### Agreed interactions

Selecting a ready unit immediately shows movement range. Selecting a destination
previews a deterministic minimum-cost route and opens appropriate actions. Extend
the existing search using observed terrain/fuel/CO/occupancy rules; retain manual
route editing when the path matters or automatic routing cannot be supported.
Previews send no emulator input. Clicking the selected unit opens in-place actions.

Menus sit beside the chosen destination, constrained to the viewport; narrow
screens use a bottom action panel. Wait, Capture, Join, Supply, Dive, Rise, and
Load commit when chosen. Attack and missile launch commit on highlighted target
selection. Unload selects passengers and board destinations before a final Unload
control. Clicking an owned empty production facility opens a purchase menu with
sprites, costs, and affordability. Purchases, powers, end turn, and surrender use
concise confirmations.

Escape, right-click, and a visible Back control return through targeting,
destination selection, and unit selection, restoring board focus. Cancelling a
destination returns to the unit; cancelling again clears selection. Mouse, touch,
and keyboard paths provide the same operations. Open menus receive focus.

### Command integration and acceptance

Keep existing gameplay HTTP commands, authorization, observation schemas,
revision checks, request IDs, and recovery behavior. Only extraction, a versioned
sprite manifest, and prototype asset delivery add interfaces. Build submissions
from the final draft and committed revision rather than reading stale React state
after dispatch. Disable duplicate submissions while pending, preserve inspection,
clear stale drafts on boundary changes, and show compact command feedback near
the board, including uncertain results and rollback.

Keep the current command form until all supported actions have replacements.
Use synthetic artwork for ROM-independent tests, and verify extraction and live
play separately. Check themes, scaling, narrow layouts, keyboard/mouse/touch,
accessibility, and recovery. Require all pre-commit hooks for each completed item.
Human playtesting must cover selecting, moving, attacking, purchasing, unloading,
cancelling, ending turns, and recovering from errors; record and address friction
before accepting the redesign or resuming broader platform acceptance.

### Compact gameplay layout (2026-11-15)

After loading a match or snapshot, connection/display/import controls collapse
into a labeled settings disclosure. Export, refresh, and disconnect remain in
the header. The match HUD names the map and shows day, active player, funds,
CO identity, and charge status; native frame numbers, revisions, and identifiers
remain in match details. Player cards scroll horizontally on narrow screens so
four players do not push the board down four rows.

The inspector prioritizes HP, readiness, fuel, ammo, and present cargo/capture
progress. Exact internal health, identities, and baseline rules remain in an
expandable section. The existing command form is retained until contextual
replacement coverage is complete. These changes have synthetic component/browser
coverage; human usability acceptance and native visual acceptance remain pending.

### Destination routing (2026-11-15)

In the app, selecting a ready unit shows observed movement reach. Clicking a
reachable destination reconstructs a minimum-cost route using the existing
movement search, retaining the source unit while the inspector follows the
cursor. Enter/Space selects the destination after keyboard inspection. Routes
exclude their origin in command payloads, include it in board markers, and do
not submit emulator input until an action is chosen and confirmed by the current
controls. Equal-cost ties follow the search's fixed traversal order.

Automatic destinations can be replaced with another click. Plan movement/Edit
route manually preserves explicit adjacent-step editing, undo, and clear. Unknown
rules or fog keep automatic routing unavailable and retain the manual workflow.
Occupied allied tiles remain transit-only unless an available Join/Load action
can use that endpoint; the server remains authoritative for action legality.
The persistent command form and its confirmation flow remain until the next
contextual-menu tasks replace them.

### Ordinary contextual actions (2026-11-16)

A destination click, or a second click on the selected unit, opens a compact
viewport-constrained action menu. Narrow screens use a bottom panel. Wait and
Capture submit immediately when chosen; Attack highlights compatible enemies and
submits on target selection. Actions are constructed from the final target and
current committed revision without waiting for a React draft update.

Menus focus their first enabled action and support Up/Down/Home/End navigation.
Escape, right-click on the board, and Back return from targeting to the destination
menu, then to unit selection, then clear selection. Placement accounts for the
interface scale; browser checks cover narrow menus at 100% and 200%. Pending
commands close contextual menus and the session retains its duplicate-submission
and uncertain-retry guards.

Other actions / manual route retains the existing explicit editor while remaining
unit actions migrate. Explicit routes can open the contextual menu with Choose
action. The old command form stays available for operations not yet migrated;
its ordinary route controls are hidden during contextual board interaction.

### Specialized contextual actions (2026-11-16)

The same menu now exposes Join, Supply, Dive/Rise, Load, Unload, and missile
launch when the observed unit and destination make them relevant. Immediate
commands use the shared action constructor and capability checks. Missile launch
commits on map target selection. Explicit route editing remains accessible.

Unloading opens passenger choices and board drop highlights. Selected destinations
are marked D1/D2; another passenger's assigned tile is excluded. Choosing a drop
returns focus to the final Unload selected cargo control. Clearing a drop and Back
retain predictable editing/cancellation stages. No command is sent until that
final control is chosen. Roving board focus keeps keyboard Tab navigation from
stepping through every map tile.

Component checks cover all specialized command kinds and sequential two-passenger
Lander drops. Browser checks cover passenger selection, green drop highlighting,
D1 marking, focus restoration, absence of preview commands, and the final typed
unload request. All 103 component/unit checks and 42 browser scenarios passed.
These synthetic checks verify UI/transport behavior; live effects retain their
existing executor acceptance and await redesigned-client live playtesting.

Sprite movement/transit borders, threat hatching, and cargo markings are drawn
over artwork so they remain visible when the symbolic renderer is replaced.

### Purchases and match controls (2026-11-16)

Empty owned production facilities open a viewport-constrained catalog with
local sprites (or symbols), baseline costs, available funds, and disabled
unaffordable choices. Choosing a unit opens a confirmation; Back restores the
catalog and its selected choice. Occupied facilities remain unit selections.

Power, Super Power, End turn, and Surrender now live in the compact HUD.
All four require confirmation; end turn lists unused units and surrender
explains immediate forfeiture. Known meter/CO thresholds disable unready
powers using the current use counter. Unverified thresholds defer readiness
to the server. Next-use debit reference values retain their separate meaning
and use the backend's maximum-counter clamp.

Component checks cover readiness, confirmation, unused units, and trigger
focus restoration. Browser checks cover affordable/disabled choices,
purchase Back, cancellation by inspection, current revision requests, and
existing uncertain/failed/rollback match-control flows. The symbols-only
sidebar screenshot was reviewed after moving match controls to the HUD.
Authentic assets remain outside the repository. Live emulator and human
acceptance remain in the final playtest item.

### Integrated command feedback (2026-11-16)

All supported unit actions now use contextual menus, including routes edited
manually. The persistent action/target/purchase form and duplicate match controls
have been removed. Optional unit/facility lists and the explicit route editor
remain as selection aids. A manual route opens the same destination menu with
Choose action; Wait and Capture submit there, and Attack submits on the final
target without an additional review screen.

Command feedback is independent of the draft and stays directly below the board
while other menus are open. It covers sending, queued/running, completed,
uncertain, rejected, recovery-required, and rolled-back results. Request and
revision metadata sit in a Command details disclosure. Safe same-request retries,
status checks, error details, and the last eight actions remain available.
The shared session still enforces one pending request and validates revisions;
committed-boundary changes invalidate the action draft.

Browser checks cover all ordinary manual/automatic routes, purchase and match
controls, cargo selection, keyboard cancellation, recovery/reconnect, rollback,
stale drafts, themes, interface scaling, and narrow screens. A delayed-receipt
scenario deliberately clicks the same action twice, verifies only one server
command, and inspects another tile while sending. The final symbols-only
screenshot was reviewed. Native rendering, live game interaction, and human
acceptance remain in the playtest item.

### Live playtest follow-ups (2026-11-16)

An isolated local headless emulator/API match used the existing unlocked save
profile, current frontend build, and external ROM-extracted atlas. All generated
saves, credentials, observations, scripts, and screenshots remained in temporary
storage. The browser exercised actual facility purchase confirmations, both
players' end turns, Infantry movement into an APC, and carrier movement followed
by a passenger drop and final Unload. The resulting committed observation at
revision 7 placed the APC at (3,7), Infantry at (2,7), and both outside cargo.
No browser page errors occurred in this sequence.

A subsequent two-player tank sequence purchased both tanks through the catalog,
passed turns, moved around the mountain barrier using contextual Wait, and
committed an Attack by selecting the enemy target. The enemy tank fell from
100 to 61 internal health and the committed board refreshed. No browser page
errors occurred. The corrected open-water atlas was separately rendered against
a captured real-map observation and visually reviewed.

The first live purchase completed in about 18 seconds. This exposed the old
15-second automatic command-status polling limit, which left the UI showing
Running after the emulator committed. Accepted commands now continue polling
until a terminal result, disconnect, or request failure. A fake-clock regression
covers a command still running beyond 30 polls and completing afterward; manual
status checks and safe uncertain-request retry remain available.

The full-map preview also exposed a representative-tile choice problem: the
first Sea lookup entry is a tiny shoreline transition, repeated like islands
across all water. Comparing the same match's emulator screenshot confirmed the
palette/decoder colors; the pack now uses open-water tile 42, observed at Bean
Island (0,0). ROM-dependent checks verify the chosen pixels and unchanged source
ROM. Existing external packs need regeneration; generated artwork is not added
to the repository.

This is automated browser-driven live evidence, with screenshots reviewed by the
implementation agent. It does not provide human acceptance, native Tauri visual
acceptance, or live outage/rollback acceptance. The final redesign TODO remains
open for those checks and for any focused usability feedback.

### Human playtest feedback (2026-11-16)

The user prefers the redesigned UI so far. Follow-up TODOs are recorded in
[Milestone 4](MILESTONE-4.org):

- Make the funds, CO identity, and CO power charge display resemble the game or
  Advance Wars By Web, with a compact arrangement and readable charge/readiness.
- Make both movement and attack ranges substantially easier to see. Their covered
  tiles, boundaries, and differences must remain clear over game sprites and
  symbolic terrain, including overlapping markings.

Review these changes with the user in the live client. Human playtesting is in
progress, and final acceptance remains open pending these fixes and the remaining
playtest scenarios.

Further human testing identified four additional follow-ups:

- Join is offered for two full-health Infantry. Audit client and server rules
  together and validate the complete cartridge behavior before emulator input.
- Waiting for gameplay execution needs an obvious spinner/progress indicator
  that explains the current action, including long-running actions.
- Rejected or failed gameplay actions need prominent toast-style notifications
  with a readable reason, outcome, and recovery guidance.
- The selected unit needs an unmistakable persistent marker, distinct from
  inspection, keyboard focus, ranges, routes, and targets.

Join research: the [AWBW units reference](https://awbw.fandom.com/wiki/Units#Joining_Units)
says the destination is damaged, a full-health mover may initiate, loaded
transports cannot join, health/fuel/ammo combine, excess HP converts to funds,
and the resulting unit has spent its action. Equal health alone is not a reason
to forbid joining two damaged units. The
[command overview](https://awbw.fandom.com/wiki/Advance_Wars_Overview) describes
the destination cutoff as at most 9 displayed HP and gives a refund of 10% of
unit price per excess HP. Nintendo's
[AW2 manual](https://www.nintendo.com/eu/media/downloads/games_8/emanuals/game_boy_advance_8/Manual_GameBoyAdvance_AdvanceWars2BlackHoleRising_EN_DE_FR_ES_IT.pdf)
provides a simpler description referring to both units being damaged.
Reconcile this wording and AWBW's behavior with the actual supported cartridge,
including hidden damage, used partners, capture progress, and rounding; the ROM
remains authoritative. Current client partner selection and server preflight
lack a health gate, and the server's result check assumes the mover gains health.
These are investigation findings for the Join TODO, not an implemented fix.

Further requested follow-ups:

- Give loaded APCs, Transport Copters, Landers, and other supported transports a
  clear persistent cargo indicator on the board, with readable cargo count/status
  alongside existing HP and selection markings.
- Show an accessible toast when the authenticated player's turn begins, without
  stealing focus or repeating notifications on ordinary refreshes/reconnects.

Both are separate TODOs in Milestone 4 and remain part of human acceptance.

Human result: the user confirmed that movement and cancellation work during the
live playtest. These functional scenarios have passed human testing. The range
and selected-unit visibility findings remain open, alongside the other usability
follow-ups. Combat, cargo, purchasing/turn changes, and error recovery still need
explicit human confirmation before final acceptance.

Human result: the user confirmed that Attack works. Mark attack execution as
passed. Attack-target cancellation still needs explicit confirmation; cargo,
purchasing/turn changes, and error recovery remain in the acceptance checklist.

Human result: the user confirmed cargo works after the loading/unloading test.
Mark cargo loading and unloading as passed. The loaded-transport visibility TODO
remains open. Purchasing/turn changes, error recovery, and attack cancellation
still need explicit human confirmation before final acceptance.

Human result: the user confirmed purchasing and turn changes work after testing
purchase cancellation, the funds deduction, and unit readiness on the next turn.
Mark purchasing and turn changes as passed. Functional human passes now cover
movement/cancellation, attack execution, cargo loading/unloading, purchasing, and
turn changes. Attack-target cancellation and error recovery still need explicit
confirmation. All reported usability follow-ups and final acceptance remain open.

Human result: the user confirmed both attack-target cancellation and recovery
after a rejected Join work. The functional human playtest checklist has passed:
movement/cancellation, attack execution/cancellation, cargo loading/unloading,
purchasing, turn changes, and valid actions after rejection. This confirms the
reported recovery flow, not new live outage or rollback fault-injection coverage.

Final redesign acceptance remains open. The next work is to implement the eight
recorded usability TODOs, review those changes with the user, and complete the
remaining native visual verification. The positive functional results do not
close the Join eligibility or visibility/notification findings.

### Usability implementation: player HUD

The player overview now uses a compact CO badge/funds panel with segmented gold
Power and blue Super Power stars and a readiness/active-state label. Meters use
the verified current-use activation thresholds, distinct from next-use debits.
Unknown thresholds/readings retain explicit text instead of fabricated progress.
No new game artwork is bundled: CO identity uses a text badge. The arrangement
follows the [AWBW overview](https://awbw.amarriner.com/guide.php); final human
visual acceptance remains pending.

### Usability implementation: range visibility

Movement uses a strong blue solid fill and double edge; attack uses diagonal
stripes and a red edge. Overlaps use alternating blue/orange stripes, allied
transit uses dashed blue, and threats/drops keep distinct dashed edges. A visible
legend explains the patterns. A dedicated overlay layer sits above terrain and
below units/HP, shared by sprite and symbolic boards. Human readability review
remains pending.

### Usability implementation: Join eligibility

The supported cartridge's eligibility routine (0x08025FC0) compares owner/type,
requires empty cargo in both units, and rejects destinations whose rounded-up
HP is 10 (internal health 91–100). It does not reject a full-health mover or a
destination that has already acted. Client destination planning, menus, server
preflight, and menu recognition now agree with this behavior.

The merge routine (0x08042998) rounds each unit's HP up before summing, caps the
result at 100, combines ammo/fuel with capacity caps, converts excess displayed
HP into funds through the cartridge's CO-adjusted cost routine, copies destination
capture progress, consumes the destination, and spends the mover's action.
The executor now verifies exact combined health, ammo, destination capture
progress, and survivor identity instead of requiring a health increase. Native
execution remains responsible for fuel consumption and CO-adjusted refunds.
Regression checks cover full/full, hidden damage at 10 HP, full/damaged, equal
damaged HP, used destinations, and cargo rejection. ROM routine evidence comes
from the supported local ROM and its matching disassembly; no assets or ROM
bytes are committed. Live edge-case and user rechecks remain pending.

### Usability implementation: action progress

A sticky board-side status banner names the action and shows a spinner during
sending, queuing, and execution. Unknown outcomes use a distinct static marker
and recovery guidance. A details link reaches existing safe retry/status controls.
Reduced-motion preferences disable rotation; inspection remains available and
the shared session retains duplicate-input protection. Human review is pending.

### Usability implementation: action notifications

Persistent dismissible toasts now name rejected/rolled-back actions and explain
the cause and next step, with links to action details and a board-refresh button.
Unknown outcomes and recovery-required states have distinct guidance. Immediate
HTTP rejections retain request context, so they appear as failed actions as well
as a toast. Notices are deduplicated per request/outcome, preserve focus, and
announce errors accessibly; safe retry completion clears its unknown warning.
Human review remains pending.

### Usability implementation: acting-unit selection

The acting unit now has a persistent black/white cursor and SELECTED label.
It stays at the unit's origin while the user inspects other tiles, previews a
destination, or selects an attack target. Inspection, keyboard focus, route, and
acting-unit identity remain separate; cancellation and boundary changes clear
the marker. Its accessible tile name identifies the selected acting unit.
Human review remains pending.
