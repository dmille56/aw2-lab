# HTTP API design proposal

Status: proposed for review before implementation. This document specifies the
Milestone 3 HTTP boundary; it does not describe routes already available. The
current application exposes `/health` and mounts MCP at `/mcp`.

The API should let human and AI clients claim separate slots in one match,
observe coherent states, submit actions, and recover through checkpoints.
The initial playable configuration has two players; the planned expansion
supports matches with two, three, or four players and configurable maps, COs,
teams, fog, weather, and other match rules.
Clients should need only HTTP, JSON, SSE, PNG images, and checkpoint archives.
Both active and inactive players receive state changes without repeated polling.
HTTP and MCP adapters consume the same controller events and shared services.

## Transport decision

Use HTTP POST requests for discrete commands and SSE for server-pushed state
and command updates. This fits turn-based actions while preserving the existing
receipt, error, idempotency, and revision contract. WebSockets are excluded from
this API scope. MCP uses its supported protocol transport and the shared
controller services and event publisher.

## Contract and versioning

Use `/v1` for public resources. Keep `/health` as the existing process liveness
endpoint and `/mcp` as the MCP transport. Serve OpenAPI at `/openapi.json` and
interactive documentation at `/docs`.

JSON requests and responses under `/v1` carry `contract_version: 1`. Use the existing
Pydantic action, summary, receipt, result, and error models wherever possible.
HTTP request models omit `match_id` when it comes from the route and omit
credentials when they come from the authorization header. The adapter constructs
the controller's internal request. Reject extra fields, including duplicate
body `match_id` or `credential`, rather than silently overriding them.
HTTP response models add the contract field to dataclass payloads such as
`MatchObservation`; nested decoder payloads keep their existing schema fields.

UUIDs are strings. Unit lifetime IDs remain opaque decimal strings. Revisions
are JavaScript-safe integers. Coordinates are zero based. Decoder and
observation schema versions remain independent of the HTTP contract version.

MCP has separate protocol and application versions:

- The MCP protocol revision governs transport, framing, capabilities, and
  subscription messages. The MCP SDK negotiates/enforces supported revisions
  according to the selected protocol specification. It is independent of our
  HTTP `/v1` path and must not be replaced by the game contract number.
- The AW2 game contract versions tool arguments, structured tool results, and
  resource contents. These application payloads use `contract_version: 1`, the
  same shared models and behavior as HTTP v1. Standard MCP protocol envelopes
  and resource-update notifications retain their protocol-defined schemas.

Capabilities report `supported_game_contract_versions: [1]`. Unsupported game
contract versions fail before side effects; the adapter exposes a structured
`unsupported_feature` application error rather than silently translating them.
Keep stable tool names on `/mcp`, which initially serves game contract v1. Use
versioned resource URIs such as `aw2://v1/matches/{match}/state` so clients cannot
confuse incompatible resource contents. A future breaking game contract gets a
separate MCP endpoint, for example `/mcp/v2`, with corresponding versioned
resources; `/mcp` retains its v1 contract during any supported migration period.
Compatible additions follow the same documented schema policy and client checks
as HTTP. The MCP server package's `serverInfo.version` is an implementation
release version, not a substitute for either protocol or game contract version.

## Future matches with two to four players

Treat 2–4 player matches as a planned extension of the shared match services,
HTTP API, and MCP adapter. V1 initially advertises `supported_player_counts: [2]`
and the fixed Bean Island configuration. Advertise three- and four-player
configurations only after their maps, setup navigation, turn order, team rules,
execution, and recovery have been verified.

Design the HTTP models and clients around an ordered `slots` collection, with
stable slot identifiers and each slot's status and army/team assignment. The
initial supported values remain `slot_1` and `slot_2`; future configurations can
add `slot_3` and `slot_4`. Clients iterate the advertised collection rather than
assuming exactly two entries or deriving an opponent from their own slot number.
Player count and assignments come from validated match configuration, not from
the number of connected SSE/MCP clients. One slot can reconnect through multiple
connections, and disconnecting does not remove a player from the game.

Keep invitation, join, revocation, and authorization operations scoped to
`{match}/slots/{slot}`. Start requires every player slot configured for that match
to be joined. Operator access remains independent of player count. Every joined
player receives the same authoritative updates during active and inactive turns;
subscriptions, resources, event payloads, and command routes are shared across
player counts. Commands continue to identify one acting slot and revision.

Turn execution must use the configured army mapping, observed active player,
and AW2's turn order and outcomes. Future executors must handle eliminated armies,
day wrap, and teams; they must not assume the next player is `3 - current_slot`
or that one player's elimination ends a match. Current two-player executor
postconditions and the `external_both` configuration need explicit extension.

The existing Python contract fixes `PlayerSlot`, `MatchSummary.slots`, and the
configuration to two players. Generalizing those models is future implementation
work, with a documented compatibility/versioning decision and generated-client
checks before additional player counts are advertised. Keep the proposed HTTP
collection shape extensible now; do not claim that current models already
accept three or four players.

## Future AW2-controlled CPU players, outside v1

V1 supports only `control: "external"`, covering human clients and external AI
agent hosts. Capabilities advertise `supported_control_modes: ["external"]`.
Internal CPU control is future work and is not a v1 deliverable. Requests for
that unsupported mode must fail before match allocation or emulator input;
they must never silently create an externally controlled slot.

A future contract can add `control: "computer"` for AW2's built-in AI. Those
slots still count toward the configured 2–4 armies and specify CO/color/team,
but do not need player invitations, joined credentials, or external action
submissions. Start would require only the external slots to join. Observing
external clients would continue receiving updates during CPU turns.

That expansion requires verified CPU setup navigation and bounded frame
advancement under the same serialized controller until the next external turn
or recognized result. It must handle consecutive CPU turns, day wrap,
eliminations, timeouts, checkpoint recovery, and restore of control assignments.
While CPU activity blocks live decoding, preserve the last committed observation
and report execution status rather than treating intermediate RAM as settled.
AW2 owns CPU decisions; neither the API nor an agent-host decision loop chooses
their moves. Existing external-turn postconditions need explicit extension and
live verification before CPU control is advertised by a future contract.

## Configurable match creation

Design `POST /v1/matches` around
`{contract_version, request_id, configuration}`. The operator may omit
`configuration` to select the advertised default profile. When provided, it is
a complete configuration with a map ID, an ordered player collection, and rules:

```json
{
  "contract_version": 1,
  "request_id": "33333333-3333-4333-8333-333333333333",
  "configuration": {
    "map_id": "bean_island",
    "players": [
      {
        "slot": "slot_1",
        "co_id": "andy",
        "color": "red",
        "team_id": "a",
        "control": "external"
      },
      {
        "slot": "slot_2",
        "co_id": "max",
        "color": "blue",
        "team_id": "b",
        "control": "external"
      }
    ],
    "rules": {
      "fog": false,
      "starting_weather": "clear",
      "starting_funds": 1000,
      "day_limit": 30,
      "co_powers": true
    }
  }
}
```

This example represents the initial fixed configuration through the extensible
creation shape. HTTP, SDK, and MCP use the same configuration schema and shared
validation service. Map and CO identifiers are stable catalog IDs, independent
of display labels and emulator memory values. Player count is derived from the
player collection; each configured slot gets its own invitation and identity.

Initially accept only configurations matching that verified profile. Other
known maps, CO selections, player counts, fog/weather settings, team layouts, or
rule values return `unsupported_feature` until supported. Do not silently replace
caller choices with defaults. Unknown identifiers or malformed values return
`invalid_request`. JSON/schema failures and unsupported choices use `422`, with
bounded field-specific details and no credential echoes.

Capabilities expose the default configuration profile, available verified
profiles with their complete configurations, supported player counts, and map,
CO, player-assignment, and rule-option descriptors. In the initial release these
describe only the fixed profile. A client can construct the example above from
capabilities without hard-coding Bean Island, Andy, Max, or the rule values.
Future releases expand the advertised catalog/options and verified combinations.
Lists of individually supported values do not imply their Cartesian product is
supported: creation validates the entire combination against verified profiles
or explicitly advertised combination constraints.

Before allocating a match or touching the emulator, validate map/player-count
compatibility, unique slots and colors, valid CO/team/control assignments, rule
ranges, and the complete supported combination. Only external control is supported
in v1; internal CPU control belongs to the future extension above. The start
operation then navigates and verifies the accepted map,
roster, and rules; an unexpected actual setup fails through recovery instead of
publishing the requested configuration as if it had been observed.

Persist the canonical resolved configuration in `MatchSummary`, setup metadata,
and checkpoints. Include it in creation request deduplication. Identical retries
return the original match; changed settings under the same request ID conflict.
For an originally omitted configuration, retain the first resolved default so
retry behavior cannot change when capabilities/defaults change. Configuration is
immutable after creation; choosing different settings requires closing the match
and creating another. Restore must validate the stored configuration against
runtime support and preserve it, rather than substituting current defaults.

New choices require corresponding verified setup navigation, observations,
executors, and recovery behavior before advertisement. In particular, fog needs
explicit supported observation/visibility semantics, and different COs can alter
costs, movement, and other preflight assumptions. Advertising a rule such as CO
powers does not by itself advertise a new CO-power activation action. Future
extensions must follow the compatibility policy for enums, fields, and generated
clients; retain the match-creation endpoint and configuration structure.

The current `FixedMatchConfiguration` uses fixed fields such as `player_1_co`
and `external_both`. Adopting this proposed collection-based transport schema
requires an explicit model/adapter change before the HTTP v1 schema is finalized.
It does not make unverified configurations executable today.

## Resource routes

`{match}` and other resource identifiers below are UUIDs.

| Method and route | Purpose | Success |
| --- | --- | --- |
| `GET /health` | HTTP liveness and existing process status | `200`, existing health document |
| `GET /v1/readiness` | Emulator, bridge, queue, recovery, and match readiness | `200`, readiness document |
| `GET /v1/capabilities` | Supported configuration, operations, actions, limits, and availability | `200`, capabilities document |
| `POST /v1/matches` | Validate a configuration and create a match in `setup`; initially the fixed profile only | `201`, `MatchSummary` and `Location` |
| `GET /v1/matches` | Discover locally retained match summaries | `200`, `{contract_version, matches}` |
| `GET /v1/matches/{match}` | Inspect match metadata | `200`, `MatchSummary` |
| `POST /v1/matches/{match}/slots/{slot}/invitations` | Operator issues an expiring invitation for an open setup slot | `201`, invitation reference without its secret |
| `POST /v1/matches/{match}/slots/{slot}/revoke` | Operator revokes the slot credential and outstanding invitations | `200`, updated slot authorization status |
| `POST /v1/matches/{match}/slots/{slot}/join` | Claim a configured player slot; initially `slot_1` or `slot_2` | `200`, join document |
| `POST /v1/matches/{match}/start` | Queue cold boot into the match's accepted configuration | `202`, `CommandReceipt` |
| `POST /v1/matches/{match}/close` | Queue closing after earlier accepted work | `202`, `CommandReceipt` |
| `GET /v1/matches/{match}/state` | Atomic summary and last committed observation | `200`, state document |
| `GET /v1/matches/{match}/events` | Subscribe to state and command changes for either player | `200`, `text/event-stream` |
| `GET /v1/matches/{match}/observation` | Require a settled committed observation | `200`, `MatchObservation` |
| `GET /v1/matches/{match}/screenshot` | PNG from a committed boundary | `200`, `image/png` |
| `POST /v1/matches/{match}/commands` | Queue a typed gameplay action | `202`, `CommandReceipt` |
| `GET /v1/matches/{match}/commands/{command}` | Poll execution status | `200`, `CommandResult` |
| `POST /v1/matches/{match}/checkpoints` | Queue checkpoint creation | `202`, `CommandReceipt` |
| `GET /v1/matches/{match}/checkpoints` | List this match's stored checkpoint references | `200`, `{contract_version, checkpoints}` |
| `GET /v1/matches/{match}/checkpoints/{checkpoint}` | Inspect a safe checkpoint summary | `200`, `CheckpointReference` plus compatibility metadata |
| `GET /v1/matches/{match}/checkpoints/{checkpoint}/archive` | Export an opaque checkpoint archive | `200`, `application/zip` |
| `POST /v1/matches/{match}/checkpoints/import` | Validate and store an archive without loading it | `201`, `CheckpointReference` |
| `POST /v1/matches/{match}/checkpoints/{checkpoint}/restore` | Queue same-match restore | `202`, `CommandReceipt` |

Operator-only discovery returns retained summaries in creation order. Invited
players receive their match ID with their invitation. Only one non-closed
match is allowed. Closed summaries remain inspectable for the server lifetime;
durable retention of all historical matches is outside this first API.

Creation accepts the configuration request described above. Every configured
player slot must join before explicit `start`; joining the last slot must not
start the emulator implicitly. Start and restore never accept ROM
paths, save paths, emulator executables, or client-supplied observations.

## Authentication, permissions, and joining

Authentication is required in v1. Use opaque bearer tokens and a shared
authorization service for HTTP, SSE, and MCP. Only `/health` and the non-sensitive
capabilities document are public. Readiness, match discovery, and match data
require authorization. A match UUID, request ID, invitation reference, or stream
connection ID is never itself permission to access a resource.

There are two credential types, with one bearer credential per request:

- An operator credential authorizes server and match administration. Provision it
  through trusted local setup and load it from an operator-owned secret file at
  startup. Require it before enabling the public match routes; never generate a
  token in an HTTP response, accept a secret-file path from a client, or print the
  token in diagnostics. Raw operator tokens stay outside Git and the Nix store.
- A player credential authorizes one claimed match slot. It grants full shared
  observation access for that match and gameplay for its own active slot. It
  cannot create matches, invite players, or enable debug access.

| Operation | Operator | Joined player |
| --- | --- | --- |
| Read readiness, discover matches, create a match | Allowed | Denied |
| Issue invitations or revoke slot access | Allowed | Denied |
| Read a match summary, state, screenshot, events, or command status | Allowed | Own match only, during either player's turn |
| Start or close a match | Allowed | Denied |
| Submit gameplay | Use a separately claimed player credential | Own slot and active turn only |
| Create a checkpoint, list references, or read safe compatibility metadata | Allowed | Own match only |
| Export/import archives or restore a checkpoint | Allowed | Denied |
| Debug operations | Allowed only when startup debug option is enabled | Denied |

Keep operator credentials out of human player clients and agent hosts that only
play. A trusted operator application can create the match and distribute a
separate invitation for each slot through a private channel outside the API.

An invitation is a single-use secret bound to one match and open setup slot.
For retry-safe issuance, the operator client generates the secret with a
cryptographic random source before sending
`{contract_version, request_id, invitation_token, expires_in_seconds}` to the
invitation route. Default validity is 15 minutes, bounded to 1–60 minutes from
first issuance. The response contains an opaque invitation ID, match, slot, and
expiry, without returning the secret. An identical issuance retry returns the
original reference and expiry; it never extends the invitation's lifetime.
Store only a hash of the invitation token. Issuing a replacement invalidates
previous unconsumed invitations for that slot.

The invited player generates its own distinct player credential before joining.
The Python SDK uses `secrets.token_urlsafe(32)`; browser clients use their
cryptographic random source. The join request carries the desired new player
credential in the bearer header and
`{contract_version, request_id, display_name, invitation_token}` in its body.
At this endpoint the invitation grants authority to claim the slot; a new bearer
token alone is insufficient. Both secrets must be independently generated.

Under the controller's setup lock, validate the invitation's hash, expiry, slot,
and unconsumed status, bind the player credential hash to that slot, and consume
the invitation atomically. Return the match and player slot without a new secret.
A lost response is recoverable: the same request ID and claim payload, proved
by the already joined credential, returns the existing claim even if the consumed
invitation has since expired. Changed claim data conflicts; another credential
cannot replay the response or reuse the consumed invitation. Revocation is
checked before any deduplicated response is returned.
Claim deduplication retains secret hashes and authorization identity/generation
in the private authorization ledger; raw invitation or player tokens never enter
payload fingerprints written to the command journal. The revoke request carries
`{contract_version, request_id}`; identical retries do not revoke a later claim
or increment the authorization generation again.

Creating matches, issuing/revoking invitations, and joining are locked metadata
operations; they leave emulator frames and game revision unchanged. Persist
setup metadata, authorization generations, and their idempotency records before
acknowledging success. A recovered setup still requires explicit start. Recovering
playable game state requires a compatible checkpoint; authorization metadata
alone cannot recreate the battlefield.

Player credentials remain valid until explicitly revoked. Closing a match ends
mutation permissions and converts existing player access to read-only inspection
of retained state; closing also invalidates outstanding invitations. The operator
may revoke even that read access. Revoking a slot invalidates its current player
credential and invitations, increments its authorization generation, and closes
its SSE/MCP subscriptions and pending wait tools. Re-inviting and claiming a
replacement credential is supported only during setup in v1. Revocation during
play leaves that slot unable to act; the operator can inspect or close the match.
Revocation is not a surrender and never changes game state by itself.

Check current permissions at acceptance, on cached responses and resource reads,
and again immediately before queued work executes. Revoked queued work is
rejected. An action already executing may finish at its transaction boundary;
revocation does not introduce cancellation or partial rollback semantics.
Subscription delivery checks its current authorization generation before sending
another event, including replay; revocation drops pending delivery and closes
the stream. Bytes already sent cannot be recalled. Reconnects authenticate again.

Keep current authorization and revocation records in a durable server-owned ledger
independent of emulator checkpoints. Restore/import must never resurrect revoked
credentials or undo invitation consumption. Exported credential verifiers do not
grant access or replace this ledger. Fail recovery closed if current authorization
records needed for an adopted match are missing or inconsistent. Operator rotation
uses a controlled server restart with the replacement secret file; old operator
tokens and connections become invalid.

These are explicit proposed changes to the existing models/controller, which
currently generate a credential on an unrestricted slot join and authorize some
administrative operations with either player's credential. Add a revoked slot
status and typed invitation references. Preserve the game/player credential
separation when implementing shared services; update `MATCH-CONTRACT.md` then.
Raw credentials and invitation secrets must never enter durable journals, access
logs, validation errors, URLs, examples, or OpenAPI defaults. Secret request fields
must be redacted, including on rejected joins and invitation issuance.

Loopback binding remains the default. Require HTTPS for connections outside
loopback, including SSE and remote MCP. Browser cross-origin access is disabled
unless an exact origin allowlist is configured. Protected responses use
`Cache-Control: no-store`. Human and AI players share these permissions; all
joined players can read the same full observation. V1 has no account/password system.

## Commands and lifecycle

All operations that change the emulator use the controller's serialized queue.
The HTTP handler returns after durable acceptance, without waiting for gameplay
to finish. Every queued POST body includes `contract_version`, `request_id`, and
`expected_revision`, with the close exception below.

Example gameplay request:

```http
POST /v1/matches/11111111-1111-4111-8111-111111111111/commands
Authorization: Bearer <slot credential>
Content-Type: application/json

{
  "contract_version": 1,
  "request_id": "22222222-2222-4222-8222-222222222222",
  "expected_revision": 7,
  "player_slot": "slot_1",
  "action": {
    "kind": "move_wait",
    "unit_id": "12",
    "path": [{"x": 4, "y": 3}, {"x": 4, "y": 4}]
  }
}
```

The action union contains `move_wait`, `move_attack`, `move_capture`, `purchase`,
`end_turn`, and `surrender`. Paths are explicit and may be empty. The HTTP layer
does not predict legal moves, damage, or randomness.

An accepted response is the existing `CommandReceipt`, with a `Location` header
pointing to its status route. `accepted_revision` means the submitted expected
revision, as in the controller today; it does not prove execution-time validity.
Clients normally receive `command.updated` events until `completed`, `rejected`,
`rolled_back`, or `recovery_required`. The status route remains available for
one-off reconciliation after disconnects and for clients that choose polling.
Status reads return `200` even when the command has failed: the failure is
represented in `CommandResult.error`.

Authenticate and validate shape before acceptance. Ownership, active turn,
expected revision, readiness, and state-dependent legality are checked again
when execution begins. Two commands queued against the same revision can both
be accepted, with the later one subsequently rejected as stale. Identical
transport retries return the original receipt, including after completion;
changed operation, route identity, or payload with the same request ID conflicts.
Disconnects and client wait timeouts do not cancel accepted work. There is no
command cancellation endpoint in this version.

Start accepts revision zero and runs navigation and initial observation capture
inside the queue. Its successful commit moves `setup` to `playable`. Close
requires `{contract_version, request_id}` but no expected revision: it is an
operator-authorized request to close after prior accepted work, allowed from setup,
playable, finished, and recovery-required. It leaves the game revision unchanged.

Gameplay, debug mutations, restore, and rollback advance the revision when a new
boundary is published. Checkpoint capture, archive import/export, and ordinary
reads leave it unchanged. A finished match keeps its terminal observation and
accepts inspection and close; gameplay is rejected. Restore is allowed only for
the existing service's same-match playable/recovery-required cases. Finished or
closed matches cannot be reopened by this API.

## Coherent state and screenshots

`GET .../state` returns:

```json
{
  "contract_version": 1,
  "summary": "<MatchSummary object>",
  "settled": false,
  "observation": "<last committed MatchObservation object, or null>"
}
```

The strings above are placeholders for nested objects. During execution the
summary reports `executing`, `settled` is false, and the observation retains its
previous committed revision. Before start it is null. The `settled`
flag means no mutation is currently executing; it does not mean gameplay is
ready, so a setup match can be settled with a null observation. The settled-only
`/observation` endpoint returns `observation_unavailable` during execution or
before an initial commit. Both endpoints read the controller atomically and
never advance frames or reconcile identities on a GET.

Screenshot capture belongs to boundary publication, with a cache of the latest
committed PNG. Publish its reference atomically with the observation. Serve that
cached image during execution, with `X-AW2-Match-ID`, `X-AW2-Revision`, and
`X-AW2-Frame` headers. Accept optional `?revision=N`: a cache mismatch returns
`observation_unavailable`; no historical image retention is promised. If capture
failed, the state can still commit but screenshot reads return unavailable.
Never capture an in-flight emulator frame and label it with the prior revision.

## SSE synchronization for all clients

`GET .../events` authenticates the operator or any joined slot before opening
a long-lived `text/event-stream` response. The inactive player has the same subscription
rights as the active player. Subscription reads never advance frames, acquire
gameplay ownership, or change revisions. Actions still enter through the command
POST route and retain their execution-time ownership and revision checks.

Use the controller's shared event publisher, independent of both HTTP and MCP.
Publish committed state and command transitions after their required journal
writes, in the same serialized order as controller publication. Each event has
`contract_version`, `match_id`, an opaque `event_id`, and a typed payload:

| SSE event name | Payload and meaning |
| --- | --- |
| `snapshot` | Complete state document plus the subscription cursor; sent on a fresh connection or resynchronization |
| `match.updated` | Complete state document after lifecycle/slot changes or a committed observation; includes the active player when battle data is available |
| `command.updated` | Complete `CommandResult` for queued, running, or terminal status |

Full state documents let clients replace their local state without applying
fragile deltas. A turn change is visible in `match.updated`; clients compare its
active slot with their own. Normal gameplay observations are published only at
verified command boundaries, including rollback and restore. An `executing`
lifecycle update still carries the last committed observation with
`settled: false`. This stream synchronizes authoritative game state; intermediate
animation frames would require a separate presentation feature.

For a completed mutation, publish the new state before its terminal command
event. A client receiving terminal completion can therefore already hold the
matching state. Setup joins and close also produce state events even when the
game revision is unchanged. Screenshot bytes stay on the PNG endpoint; clients
fetch the revision-associated image when needed, without polling for changes.

The SSE `id` field matches `event_id`. Use a server-run UUID plus a monotonically
increasing sequence, such as `<run UUID>:<sequence>`, opaque to clients. Event
sequence is distinct from game revision: command status and lifecycle events
can share a revision. On reconnect, accept `Last-Event-ID` and replay subsequent
events when retained. Duplicate delivery is possible; clients discard already
processed IDs. A new server run, unknown cursor, or expired replay window causes
a fresh `snapshot` with `resync: true`, not a claim that all missed events were
replayed. After resynchronizing, clients fetch the status of any tracked commands
whose terminal result they missed. No durable event history is promised.

Register subscribers and obtain the initial state/cursor atomically with
publication so a commit cannot fall between snapshot capture and subscription.
Retain at most 256 events or 16 MiB per match for replay, whichever is reached
first. Bound each subscriber's pending buffer to 128 events or 8 MiB. Disconnect
a slow subscriber when either limit is reached; it can reconnect and replay or
resynchronize. Network writes never hold controller locks or block the emulator
queue. Advertise these bounds in capabilities.

Send SSE comment heartbeats every 15 seconds without advancing event IDs or
emulation. Disable proxy buffering and compression that delays event delivery.
On close, deliver the final closed state and end the stream; a new subscription
to that retained closed match receives a final snapshot and then ends. Server
shutdown closes streams, and reconnects follow normal readiness rules.

Browser clients use a fetch-based SSE reader to send the bearer authorization
header. Native `EventSource` cannot supply that custom header. Credentials must
never be moved into query strings to make subscriptions work. Reconnects
authenticate again; stream connection IDs never grant mutation authority.

## MCP integration and agent-host responsibilities

Expose match state and command status as MCP resources, for example
`aw2://v1/matches/{match}/state` and
`aw2://v1/matches/{match}/commands/{command}`, and gameplay as typed tools backed by
the same services as HTTP. The in-process MCP adapter subscribes directly to the shared
event publisher. A separately deployed adapter may consume the HTTP SSE endpoint.
Neither adapter creates another emulator, game state store, or mutation queue.

Map authenticated MCP callers to the same operator/player principals and enforce
the permission table on every tool, resource read, subscription, and replay.
The server-side adapter receives validated identity from its transport context;
model-supplied slot names and tool arguments cannot grant operator permissions.
Remote MCP must use authentication supported by its negotiated protocol and host,
mapping that transport identity to the shared permissions. Keep remote access
disabled until the selected SDK can enforce that mapping; an MCP connection or
session is not an authorization bypass. Player revocation closes notifications
and waits for that principal just as it closes HTTP SSE.

Map state changes and command transitions to standard MCP resource-update
notifications for authorized subscribers to the respective resources. The client
reads the resource after notification; this is an
event-triggered read, not repeated polling. Use the subscription mechanism
supported by the negotiated MCP protocol and SDK: earlier versions use resource
subscribe/unsubscribe, while the 2026-07-28 protocol uses `subscriptions/listen`.
Do not send raw application SSE event envelopes on the MCP endpoint. MCP handles
its own framing and notifications; the HTTP event stream's replay contract does
not imply MCP transport replay support. Read authoritative state on initial
subscription and reconnect, and advertise subscription support only after it is
implemented and verified with the selected SDK/client versions. See the
[earlier resource subscription specification](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
and [2026-07-28 streaming transport specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx).

The server supplies observations, notifications, action tools, turn enforcement,
and recovery. The agent host owns the decision loop: receiving updates, invoking
the model, choosing an action, and submitting it when its slot is active. The
API/MCP server does not schedule model turns or choose strategies. A notification
alone does not guarantee that a particular host will invoke its model; the host
must implement that behavior. Human clients can render the same state updates.

For hosts that cannot consume subscriptions, plan an optional bounded MCP
`wait_for_turn(match_id, player_slot, after_revision, timeout_seconds)` tool.
It waits on the shared publisher and returns a current state when that slot is
at a ready playable boundary newer than `after_revision`, the match finishes,
closes, or requires recovery, or the timeout expires. It checks current state
before waiting and registers without a race. Bound waits to 60 seconds; a timeout
returns an explicit `timed_out` outcome and the current state without failing or
cancelling a gameplay command. Waits never reserve the turn, hold the mutation
queue, or advance frames. The host still decides the next action, and submitted
actions must use the returned revision. Keep this tool in the MCP adapter/client
milestone; HTTP SSE does not depend on implementing it.

## Checkpoint transfer

Create and restore use command receipts and status events, with status GETs
available for reconciliation. A successful result carries
`checkpoint_id`; restore may return a new checkpoint ID representing the new
monotonic revision. Import stores an archive without mutating the running match,
so it returns a reference synchronously and does not create a command.

Import uses an `application/zip` body, the operator bearer credential, and a
`Request-ID` UUID header because its body is binary. Include the archive digest
in deduplication. Repeating the same import returns its original reference;
changed bytes under the same request ID conflict. Bound the raw upload before
decoding to `MAX_ARCHIVE_BYTES` (4 MiB + 64 KiB), and retain the store's strict
member, decompression, digest, and compatibility checks. Imported checkpoints
must belong to the current match. A rejected archive never changes CURRENT or
emulator state.

Checkpoint JSON reads expose only reference and compatibility fields, excluding
credential verifiers and local storage paths. Explicit binary exports contain
the existing full manifest, including one-way credential verifiers, and save RAM;
only the authenticated operator can download them. Use a server-generated
attachment filename based on the checkpoint UUID.

## Debug operations

Debug access requires an explicit server startup option, disabled by default,
plus the operator credential. Player credentials never authorize debug access.
Disabled operations return `unsupported_feature`.

| Method and route, under `/v1/matches/{match}/debug` | Payload or response |
| --- | --- |
| `POST /buttons` | Common command fields plus named `buttons` and `frames` |
| `POST /frames` | Common command fields plus `frames` |
| `POST /memory/read` | `contract_version`, `expected_revision`, `address`, `length`; synchronous coherent read with match/revision/frame and base64 bytes |
| `POST /memory/write` | Common command fields plus `address`, base64 `data` |
| `POST /reset` | Common command fields |

Button names use the recorder's established names, including `neutral`. Start
with 1–600 frames per request, at most 4,096 read bytes and 256 write bytes.
Return these bounds and permitted memory regions in capabilities. Memory reads
use a serialized read barrier and recheck the revision at that barrier; they
do not change the revision. No request may bypass queue ownership to reach Lua.

Debug mutations must publish a newer observation, even when reset or a memory
write leaves battle data unavailable. Such an observation records unavailable
identity/readiness and requires restore before gameplay resumes. This needs an
explicit tracker/controller path for unavailable debug boundaries; the current
playable and terminal commit methods cannot supply it. Never invent a playable
state to satisfy the existing executor interface.

## Errors, limits, and readiness

Use the existing `ErrorResponse` for all JSON errors, including FastAPI validation
failures and unexpected exceptions. Preserve `request_id` when it was parsed.
Validation details name fields and constraints without echoing submitted values.
Unknown exceptions return a generic `internal_error`; diagnostics stay local and
redact credentials and server paths.

| HTTP status | Error codes or condition |
| --- | --- |
| `400` | Malformed JSON or invalid archive structure (`invalid_request` / `checkpoint_corrupt`) |
| `401` | Missing or invalid credential; include `WWW-Authenticate: Bearer` |
| `403` | Valid credential with insufficient permissions (`permission_denied`), or invalid/expired invitation (`invalid_invitation`) |
| `404` | Unknown match, command, or checkpoint |
| `409` | Lifecycle/ownership conflict, wrong turn, stale revision, unavailable observation, recovery-required, incompatible checkpoint, request-ID conflict |
| `413` | Request/archive exceeds advertised bounds (`invalid_request`) |
| `415` | Unsupported request media type (`invalid_request`) |
| `422` | Valid JSON with invalid schema or `unsupported_feature` |
| `429` | `command_capacity`; include `Retry-After: 1` |
| `503` | Server stopping, unavailable configured storage/journal, or required runtime service unavailable |
| `500` | Unexpected internal failure |

Add `checkpoint_not_found` to the error enum for consistent checkpoint lookup.
An archive found on disk but failing integrity checks is `checkpoint_corrupt`,
not not-found. Runtime service absence needs a distinct `runtime_unavailable`
code. Add `permission_denied` and `invalid_invitation` for the authorization
cases above; revoked credentials use `invalid_credential`. These are proposed
additive error codes to document in the shared contract.

Bound ordinary JSON request bodies to 64 KiB, movement paths to 4,096 coordinates,
and display names to 1–80 trimmed characters. OpenAPI and capabilities expose
these bounds. Memory and archive transfers have their separate limits above.

Readiness returns independent fields for HTTP responsiveness, emulator process
state, bridge connectivity/protocol readiness, queue acceptance, recovery status,
and current match lifecycle/readiness. No frame advancement is used to probe it.
A responsive server with no match is healthy. Readiness is informational and
returns `200`; operation endpoints return the appropriate unavailable error when
their prerequisites are missing. Keep the existing `/health` payload compatible.

Capabilities distinguish `implemented`, `available` for this server run, and
verification scope. Advertise the fixed configuration, supported operation/action
names, debug enablement, production unit subset, limits, and unavailable reasons.
Expose supported player counts and the configured slot collection; initially only
two-player matches are available, with 3–4 player support reserved for later work.
Include event-stream support, event schema, heartbeat and buffer/replay limits;
report MCP subscription support separately from HTTP SSE availability.
Report the shared game contract versions independently of MCP protocol support,
and advertise only external player control for v1.
Expose the configuration profiles, catalogs, option bounds, and combination
constraints described above; distinguish planned choices from currently accepted
configurations so clients cannot mistake future support for runnable setup.
Do not advertise the current static six-action list as executable unless runtime
dispatch, session ownership, and recovery providers are configured. Keep existing
live-verification gaps for purchasing and turn actions visible in the docs.

## Implemented shared models

`api_contract.py` now defines the collection-based v1 configuration, operator/player
principals, invitation and revoked-slot metadata, lifecycle/gameplay/checkpoint/debug
requests, and safe response documents. Existing command receipts/results, action
models, checkpoint references, and error envelopes are reused from `match_contract.py`.
`api_validation.py` validates complete configurations and maps safe errors to HTTP
statuses and headers. These modules are shared by future HTTP, SDK, and MCP adapters;
they do not implement routes or authenticate callers.

Only `bean_island_v1` is accepted. The recognition catalog contains Bean Island and
AW2 CO IDs; a recognized CO outside the verified assignment is unsupported, whereas
unregistered map/CO IDs are invalid. Capabilities describe the accepted profile and
options separately from recognition. Feature availability must be supplied by runtime
wiring; no gameplay actions or event transport are marked available by default.

`resolve_configuration` resolves an omitted configuration for first creation. The
metadata service must persist that resolved value and consult its deduplication
record before resolving retries. Explicit null and incomplete configurations are
invalid. `configuration_to_controller` validates before adapting to the legacy flat
shape; reverse conversion preserves stored rule values and does not claim those
values remain supported. Controller/checkpoint storage still uses its existing schema.

Invitation secrets are `SecretStr`, excluded from request serialization and repr.
Services must explicitly hash them for the authorization ledger; dumping the model
cannot be used to fingerprint secret-bearing claim payloads. Pydantic's raw errors
can contain attacker-supplied keys even with input hiding: adapters must use
`validation_error`, which emits bounded schema-owned field paths without input,
validator messages, or context. `internal_error` produces a generic safe envelope.
Ordinary JSON byte limits still require enforcement at the future HTTP boundary;
model validation enforces paths, names, invitation lifetimes, frames, and memory bounds.
Memory-region permissions still belong to the service layer.

The existing unrestricted join/controller authorization behavior has not changed.
Durable authorization, permission enforcement, queued runtime wiring, screenshots,
events, and routers remain implementation steps 2–4 below. The game contract version
is independent of MCP protocol negotiation; these models do not enable remote MCP.

## Implementation sequence and acceptance

1. Finalize HTTP request/response models and update the credential proposal in
   the shared contract. Add explicit bounded inputs, error mappings, and examples.
   Define typed operator/player principals, invitations, and revoked slot status.
   Define MCP application payload/resource versioning independently of the MCP
   protocol revision, using the same game contract versions as HTTP.
   Define canonical configuration/player/rule models and capability-driven
   validation, initially restricted to the single verified configuration profile.
2. Add operator provisioning, durable authorization/setup metadata and request
   deduplication, invitation-gated claims, revocation, and shared permission checks.
   Adapt checkpoint and controller services to authenticated principals instead
   of treating every joined player credential as administrative access. Implement queued
   start, with navigation, shared tracker/session, action dispatcher, checkpoint
   service, and recovery providers wired to the same emulator instance.
3. Add boundary screenshot publication, unavailable debug-boundary support, and
   the shared event publisher with atomic subscription, ordering, bounded buffers,
   and replay/resynchronization. Controllers own locking and queue invariants.
4. Add thin routers for system, matches, events, commands, checkpoints, and debug.
   Use common authentication and exception handlers; keep emulator code out of
   routes. Preserve shared-service access for the MCP adapter.
5. Verify HTTP behavior with injected services and no ROM: lost-response retries,
   authentication on cached responses, simultaneous actions, execution-time stale
   revisions, screenshot races, terminal inspection, recovery, archive bounds,
   schema/error redaction, and startup/shutdown readiness. Cover both players'
   subscriptions, snapshot/subscribe races, terminal ordering, replay/duplicates,
   expired cursors and server restart, slow subscribers, and stream authorization.
   Check unauthenticated creation/join rejection, every role/resource boundary,
   invitation expiry/replacement/consumption, lost join responses, revoked queued
   commands and streams, operator rotation, read-only access after close, and
   checkpoint restore/import never undoing revocation. Include authorization
   ledger loss/corruption and secret redaction on every rejected setup request.
   Check omitted/default and explicit configuration creation, changed settings
   under a reused request ID, invalid map/roster/rule combinations, unsupported
   choices, configuration persistence/restore, and setup observations disagreeing
   with the accepted configuration. Keep 3–4 player and alternate-setting live
   verification as prerequisites before advertising those options.
   Verify MCP resource notifications separately with supported clients, including
   the host-owned decision loop and optional bounded wait tool. Then use opt-in live
   checks for cold boot through HTTP and action execution in both emulator modes.

The HTTP API task is complete only when these routes run through configured
runtime services. Publishing OpenAPI for adapters backed solely by test doubles
does not complete playable integration.
