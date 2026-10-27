# Milestone 3 public match contract, version 1

This document and [`aw2_lab.match_contract`](../src/aw2_lab/match_contract.py)
define the fixed playable configuration and the shared Python/HTTP/SDK model
surface. This is a contract proposal for implementation; it does not claim that
the controller, routes, or durable command handling already exist. The Pydantic
models are the schema source for the eventual HTTP OpenAPI document and generated
non-Python client types.

## Fixed match

Contract version 1 supports exactly one active local Versus match:

| Setting | Fixed value |
| --- | --- |
| Map | Bean Island (`bean_island`), built-in Versus map |
| Slot 1 | Red, Andy, Team A |
| Slot 2 | Blue, Max, Team B |
| Control | Both armies controlled by the server for their external players |
| Rules | 30-day limit, 1,000 starting funds per army, CO Powers enabled, clear starting weather |
| Fog | Disabled |

The fixed values are not caller-selectable. Match creation either uses this
configuration or fails with `unsupported_feature`; a later configurable-match
contract must advertise and version the additional choices. AW2 remains
authoritative for legal actions, combat, randomness, upkeep, and outcomes.

## Supported operations and actions

Capabilities must be fetched before match creation. Version 1 advertises match
create/join/inspect/close, structured observation, screenshots, command status,
checkpoints, and these gameplay actions:

- `move_wait`: move a unit along an explicit path, then choose Wait.
- `move_attack`: move along an explicit path, then attack a target coordinate.
- `move_capture`: move along an explicit path, then capture.
- `purchase`: buy a unit at an owned production property.
- `end_turn` and `surrender`.

Coordinates are zero-based `(x, y)` pairs. Every movement action carries a path;
an empty path means the unit stays on its current tile. A unit ID is an opaque
decimal string assigned by the server for one unit lifetime, not an AW2 RAM slot.
Map-bound checks and game legality are decided during command execution; invalid
requests may be rejected earlier when their shape or known state is invalid.

The following are explicitly unsupported in version 1: multiple active matches;
selectable map, CO, rules, weather, or teams; fog; activating CO Powers; transport
loading/unloading; resupply; campaign or other non-Versus modes; player-specific
visibility isolation; and arbitrary memory writes as gameplay. Unsupported
features are distinct from actions that AW2 rejects as illegal.

## Typed documents and versioning

Public Pydantic models live in `aw2_lab.match_contract`. Every contract document
contains `contract_version: 1`; unknown fields are rejected. A breaking change
requires a new contract version and explicit compatibility policy. Additive
fields require a documented compatibility decision and generated-client schema
checks. Game-state decoder schema versions and unit-identity metadata versions
remain separate from this API contract version.

The Pydantic model family covers:

- `Capabilities`, `FixedMatchConfiguration`, `MatchSummary`, and slot status.
- `CommandRequest`, the discriminated gameplay action union, `CommandReceipt`,
  and `CommandResult`.
- Stable `ErrorCode`, `ErrorBody`, and `ErrorResponse` envelopes.
- `CheckpointManifest` and `CheckpointReference`.

Match IDs, command IDs, checkpoint IDs, and request IDs are UUIDs. Revisions are
nonnegative integers no greater than `2^53 - 1`, so browser clients can represent
them exactly. The versioned `GameState` remains a pure decoder payload. The
versioned `MatchObservation` wraps it with `match_id`, `revision`, identity
status, per-unit lifetime IDs keyed by decoder reference, and action readiness.
The wrapper is implemented by `aw2_lab.match_observation`; it does not alter the
existing GameState schema. IDs are decimal strings so they remain exact in
JavaScript clients.

Lifecycle values are `setup`, `playable`, `executing`, `finished`,
`recovery_required`, and `closed`. `playable` means the match is at a coherent
command boundary; it does not imply a particular submitted action is legal.
`executing` is not a settled state. `current_state()` atomically returns the
summary and last committed observation; while a command runs, that snapshot
reports `executing`, keeps the prior revision, and sets `settled` to false.
`current_observation()` rejects reads during execution so a prior observation
cannot be mistaken for the current playable boundary. When execution completes,
the controller publishes the new observation and summary together at the next
command boundary. A finished match remains inspectable but accepts no gameplay
commands. Recovery-required blocks mutations until an explicit successful
restore. Closed matches cannot be reopened.

`ActionReadiness` describes whether the observed phase and UI boundary are
recognized for beginning a command. `ready` is not a move validator and does
not promise that a specific unit, route, target, purchase, or turn action is
legal. Unknown RAM and UI fields remain unavailable/unknown in `GameState`.

## Commands, revisions, retries, and credentials

Each mutation includes `match_id`, `player_slot`, that slot's credential,
`expected_revision`, a unique `request_id`, and a typed action. The controller
checks lifecycle, slot ownership, credential, active turn, revision, and action
readiness when execution starts. A stale revision fails with `stale_revision`;
the client must fetch current state and make a deliberate new request.

Accepted work returns a `command_id` and `queued` status. Clients poll command
status until `completed`, `rejected`, `rolled_back`, or `recovery_required`.
`running` may be reported while polling. A client polling deadline does not
cancel the command. On transport retry, the client must resend the same request
ID and identical payload. The server returns the original receipt/result for an
identical retry and returns `request_id_conflict` if that ID was used with a
different payload. Credentials are excluded from logs, diagnostics, and
idempotency payload comparison.

On successful completion, the result names the resulting revision. A rejected
command does not advance gameplay revision. Rollback restores the prior game
boundary but issues a fresh monotonic revision so stale clients cannot act on
pre-rollback assumptions. Failed rollback transitions the match to
`recovery_required`.

The match observer advances revisions only when the controller commits a new
boundary after a mutation. It supports explicit revision causes for debug
mutations, rollback, and restore. `read()` returns the last immutable committed
observation without calling the emulator, advancing frames, reconciling unit
identities, or changing the revision. Controller clients use `current_state()`
for a coherent lifecycle/observation pair; its lock ensures the summary and
observation revisions agree. Screenshot metadata binds an image to that
observation's match ID, revision, and frame; image capture itself does not
publish a new observation.

The server creates a high-entropy credential for each slot at join time and
returns it only in that join response. Credentials are sent in the request body,
held in client memory by default, never placed in URLs, and never returned by
match inspection. They coordinate trusted local players and do not provide
competitive isolation. Credentials are independent of the request ID and are
not persisted in ordinary checkpoint metadata.

## Controller queue behavior

`MatchController` is the single in-process owner of active match records and its
one FIFO mutation queue. Its default queue capacity is 64 pending commands and
its in-memory command/idempotency history is capped at 4,096 entries. A full
queue or history rejects new work before acceptance with `command_capacity`.
Accepted work has a command ID and remains tracked through a terminal status.
Gameplay commands, setup activation, debug/frame/input operations, and
checkpoint/restore callbacks use the same serialized lane; client-facing routes
must expose only fixed named operations, not arbitrary callbacks.

The controller validates player credentials, active slot, expected revision,
turn, lifecycle, and readiness at execution time. Only one command runs at a
time. A disconnect or client polling timeout does not cancel accepted work.
Gameplay completion requires a new observation for the same match at a newer
revision. The controller validates the full outcome before publishing its
observation and summary together; invalid outcomes leave the prior committed
boundary available and put the match into recovery-required state.

Shutdown stops acceptance and drains accepted work for up to 30 seconds. If the
deadline expires, the in-flight operation is marked `recovery_required` and
queued-but-unstarted work is explicitly rejected with `server_shutting_down`.
The worker exits after the current callback even if that callback catches
cancellation, and late outcomes cannot replace committed state or command
results. A separate cancellation grace period defaults to one second. If the
callback still has not returned, shutdown raises an explicit recovery error;
the API lifespan still runs emulator cleanup. Python callbacks must cooperate
with cancellation to terminate their own work.
An unexpected executor failure also blocks further mutations until recovery.

The initial request-ID ledger is in memory. Durable deduplication across process
restart is added with the command journal in the persistence task. The controller
can be created without an action executor for ROM-independent coordination
checks; gameplay requests are rejected as unsupported until a verified executor
is configured. The API application owns the controller instance at
`app.state.match_controller`; public routes are implemented in the next API task.

## Errors and checkpoints

Errors use the stable `ErrorCode` enum and carry a human-readable message, a
`retryable` flag, and bounded structured details. Clients should branch on the
code, not message text. The initial codes distinguish malformed requests,
unsupported features, missing/closed/finished matches, slot and credential
errors, wrong turn, stale revisions, request-ID conflicts, unavailable
observations, action rejection, timeout, rollback failure, recovery-required,
incompatible checkpoints, and internal errors.

The versioned `CheckpointManifest` records a complete `MatchSummary`, ROM
SHA-256, emulator build and frontend mode, decoder/observation schema versions,
last frame, and typed unit-identity ledger metadata. It points to an opaque mGBA
state artifact by format, byte length, and SHA-256. The artifact must include
save RAM; the bridge saves and loads states with `SAVESTATE.ALL`. Manifest and
artifact are separate so large binary state data does not enter JSON. The
manifest schema has its own version in addition to the public contract version.

On restore after restart, the observer requires the durable journal's revision
high-water mark and starts above both it and the checkpoint revision. Restoring
a checkpoint alone is not sufficient to guarantee revisions never repeat after
restart. Storage format, atomic commit order, journal linkage, and compatibility
checks are implemented in the checkpoint/persistence tasks; clients cannot
supply arbitrary filesystem paths.

## HTTP mapping

The route set is implemented in the later HTTP API task. Planned resource
operations are capabilities, match create/join/inspect/close, observation and
screenshot reads, command submission/status, and checkpoint create/export/import
and restore. All mutation routes use the same command queue and revision rules.
Health reports server/emulator availability only and never implies a playable
match. The API binds to loopback by default.
