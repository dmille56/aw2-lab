# MCP v1 contract and adapter design

Status: implemented contract and adapter design for Milestone 4. The
[typed lifecycle, gameplay, observation, and checkpoint tools](MCP-TOOLS.md),
[authorization boundary](MCP-AUTHORIZATION.md),
[resource notifications](MCP-NOTIFICATIONS.md), and
[bounded turn wait](MCP-TURN-WAIT.md) have ROM-independent checks. Live host
interoperability and emulator verification remain subsequent tasks. The
[SDK compatibility audit](MCP-COMPATIBILITY.md) records the pinned baseline;
[host integration guide](MCP-INTEGRATION.md) documents connection and use.
The [HTTP design](HTTP-API-DESIGN.md) remains authoritative for shared behavior.

## Boundary and versioning

Mount Streamable HTTP at `/mcp` in the existing API process. The adapter calls
`AsyncAW2Client` against the configured local API address. The application owns
one runtime, controller, queue, authorization ledger, checkpoint store, and
journal. SDK calls perform operations through those services; the adapter uses
the shared in-process publisher only for resource notifications and bounded
waits. Notification payloads trigger authorized SDK reads of committed state.

Every application tool accepts `contract_version: 1` (default 1); reject other
versions before SDK calls or side effects. Shared models provide argument and
result schemas, including their existing bounds and extra-field rejection.
MCP protocol negotiation, decoder schema versions, and server version remain
independent. Keep stable tool names at `/mcp`, version resource URIs, and reserve
`/mcp/v2` for a future breaking application contract as specified by the HTTP
design. Advertise `supported_game_contract_versions: [1]` independently of
protocol and resource-subscription capabilities. Advertise features only after
implementation and verification with the pinned SDK and hosts.

## Caller context and permission table

Transport middleware validates the request bearer and resolves the existing
operator/player principal. Preserve the incoming bearer privately for a dedicated
SDK client with immutable credentials; the HTTP facade validates it again.
A request-scoped context owns and closes that client. Do not use a global SDK
client with mutable headers. Session IDs and arguments never select a principal.
Initialization and subsequent requests must meet the selected transport's auth
requirements; enforce origin policy and bind session use to the authenticated
caller. Revalidate current authorization on cached responses, reads, subscription
registration, each delivery, reconnect, and pending waits. Queue execution retains
the shared service's ownership, turn, revision, and revocation checks.

| Operation | Operator | Player | Anonymous |
| --- | --- | --- | --- |
| Capabilities | Yes | Yes | Yes |
| Readiness, list/create matches | Yes | No | No |
| Inspect match, state, observation, screenshot, commands | Yes | Own match | No |
| Issue invitations, revoke slots | Yes | No | No |
| Join setup slot | Invitation plus independently generated player bearer | Same claim proof | No |
| Start, close | Yes | No | No |
| Six gameplay actions | No; use separate player bearer | Own active slot | No |
| Create/list/inspect checkpoints | Yes | Own match | No |
| Export/import/restore checkpoints | Yes | No | No |
| Debug operations | Startup opt-in required | No | No |
| State/command subscriptions | Yes | Own match | No |
| Wait for a slot's turn | Any slot in match | Own slot | No |

Closed matches retain authorized inspection; revocation removes it. Restoration
never restores credentials or undoes revocation. Resource discovery must not
reveal other matches or secret-bearing metadata. A stable tool catalog may list
operator operations for players; discovery does not authorize their invocation.

Invitation and join are trusted host provisioning operations using SDK `invite`
and `join`, not model-visible secret arguments. The host generates independent
invitation/player secrets, retains exact request IDs for retries, and invokes the
existing HTTP routes through those SDK methods. MCP model tools start with an
already provisioned bearer. This deliberately keeps invitation issue/claim out
of `tools/list`; document these host operations alongside MCP connection setup.
Neither bearer tokens, invitation secrets, authorization verifiers, nor secret
file paths appear in prompts, resources, diagnostics, or model tool schemas.

## Tool contract and SDK mapping

All identifiers are UUIDs except opaque `unit_id` values. Table arguments omit
`contract_version`. Mutations require a caller-generated `request_id` UUID;
never silently generate a new ID when forwarding an MCP retry. `revision` below
means the shared nonnegative `Revision` type. Results are JSON serialization of
the named shared models unless a representation is explicitly defined below.

| Tool | Arguments | SDK operation / result |
| --- | --- | --- |
| `get_capabilities` | none | `capabilities` / `CapabilitiesResponse` |
| `get_readiness` | none | `readiness` / `ReadinessResponse` |
| `create_match` | request_id, optional configuration | `create_match` / `MatchSummary` |
| `list_matches` | none | `list_matches` / `MatchListResponse` |
| `inspect_match` | match_id | `inspect_match` / `MatchSummary` |
| `revoke_slot` | match_id, player_slot, request_id | `revoke` / `SlotAuthorization` |
| `start_match` | match_id, expected_revision, request_id | `start` / `CommandReceipt` |
| `close_match` | match_id, request_id | `close` / `CommandReceipt` |
| `get_state` | match_id | `state` / `StateResponse` |
| `get_observation` | match_id | `observation` / `ObservationResponse` |
| `get_screenshot` | match_id, revision | `screenshot` plus coherent observation metadata / image result |
| `get_command` | match_id, command_id | `command_status` / `CommandResult` |
| `wait_for_command` | match_id, command_id, timeout_seconds | bounded `wait_for_command` / wait result |
| `move_wait` | match_id, expected_revision, request_id, unit_id, path | `submit(MoveWaitAction)` / `CommandReceipt` |
| `move_attack` | preceding move arguments plus target | `submit(MoveAttackAction)` / `CommandReceipt` |
| `attack` | match, revision, request, unit, target | `submit(AttackAction)` / `CommandReceipt` |
| `move_capture` | match_id, expected_revision, request_id, unit_id, path | `submit(MoveCaptureAction)` / `CommandReceipt` |
| `purchase` | match_id, expected_revision, request_id, property, unit_type | `submit(PurchaseAction)` / `CommandReceipt` |
| `end_turn` | match_id, expected_revision, request_id | `submit(EndTurnAction)` / `CommandReceipt` |
| `surrender` | match_id, expected_revision, request_id | `submit(SurrenderAction)` / `CommandReceipt` |
| `create_checkpoint` | match_id, expected_revision, request_id | `create_checkpoint` / `CommandReceipt` |
| `list_checkpoints` | match_id | `list_checkpoints` / `CheckpointListResponse` |
| `inspect_checkpoint` | match_id, checkpoint_id | `inspect_checkpoint` / `CheckpointResponse` |
| `export_checkpoint` | match_id, checkpoint_id | `export_checkpoint` / bounded archive result |
| `import_checkpoint` | match_id, request_id, archive_base64 | `import_checkpoint` / `CheckpointReference` |
| `restore_checkpoint` | match_id, checkpoint_id, expected_revision, request_id | `restore_checkpoint` / `CommandReceipt` |
| `wait_for_turn` | match_id, player_slot, after_revision, timeout_seconds | shared publisher plus SDK `state` / turn wait result |

Use `MatchConfiguration` restricted to an advertised two-player built-in Versus map
profile, external players selected from the 19-CO roster (Andy/Max by default),
and fog off. Coordinates are zero-based
`{x, y}`. Paths explicitly list successive destination tiles, excluding the
starting tile; an empty path acts at the current tile. Unit IDs identify a
tracked lifetime, not a type or coordinate; refresh observations after restore
or identity invalidation. Direct units can move then attack; indirect units can
attack only with an empty path. Unit types and actions must be advertised by
capabilities. Do not infer legal moves from schema validity.

Debug tools require SDK additions using the existing HTTP debug routes and
`Debug*Request` / `DebugMemoryReadResponse` models:

| Tool | HTTP route suffix under match | Arguments beyond match_id/version | Result |
| --- | --- | --- | --- |
| `debug_buttons` | `/debug/buttons` | expected_revision, request_id, buttons, frames | CommandReceipt |
| `debug_advance_frames` | `/debug/frames` | expected_revision, request_id, frames | CommandReceipt |
| `debug_read_memory` | `/debug/memory/read` | expected_revision, address, length | DebugMemoryReadResponse |
| `debug_write_memory` | `/debug/memory/write` | expected_revision, request_id, address, data (base64) | CommandReceipt |
| `debug_reset` | `/debug/reset` | expected_revision, request_id | CommandReceipt |

Preserve 1–600 frames, 4,096-byte reads, 256-byte writes, and EWRAM/IWRAM
restrictions. Reads use the serialized revision barrier. Debug mutations publish
an unavailable boundary and require explicit restore before gameplay resumes.
Disabled debug returns `unsupported_feature`.

## Receipts, errors, and uncertain outcomes

Queued mutations return `CommandReceipt` immediately; acceptance is not success.
`queued` and `running` are nonterminal. `completed`, `rejected`, `rolled_back`,
and `recovery_required` are terminal `CommandResult` statuses. Inspect the result
and resulting revision before the next action. Synchronous create/revoke/import
return their shared metadata results after durable acknowledgement.

Map `APIError` to an MCP tool result with `isError: true` and structured content
`{contract_version: 1, error: ErrorBody, http_status}`. Preserve shared error codes,
messages, and safe details. A terminal command failure is a successful status
lookup containing `CommandResult.error`, not a transport failure. Unknown tools
and invalid MCP envelopes use protocol errors; application schema failures use
`invalid_request`. SDK protocol failures return a sanitized adapter error.
Transport failures return a sanitized `outcome_unknown` adapter error with the
original request ID when present; never claim the command failed to execute.
Adapter errors are explicitly separate from the shared `ErrorCode` enum.

Both wait helpers default to 30 seconds and accept 0 < timeout_seconds <= 60.
Command wait returns `{contract_version, timed_out, command: CommandResult}`,
including a final authorized status read on timeout. If that read fails, return
the corresponding error rather than inventing a status. Retrying a mutation uses
the identical request ID, caller identity, and payload. Changed payloads conflict.
Cancellation, disconnect, and expired waits release adapter work without cancelling
accepted commands or causing automatic resubmission with a new request ID.

## Resources, notifications, and waits

Expose authorized JSON resources backed by the same SDK reads:

- `aw2://v1/matches/{match}/state` returns `StateResponse`.
- `aw2://v1/matches/{match}/commands/{command}` returns `CommandResult`.

Resource templates carry no credentials. Tool observations support hosts without
resource reads. Reads never advance emulation or publish a revision. Unknown
fields, unsettled boundaries, and unavailable images remain explicit.

Use protocol-supported resource update notifications as invalidations. Register
against the shared publisher without a snapshot/subscription gap, then recheck
current authorization and read authoritative state. Bound queues to 64 pending
invalidations and subscriptions to 32 per caller and 256 per server. Coalesce
repeated URI invalidations; on overflow terminate the affected subscription with
a resynchronization diagnostic. Reconnect always reads a fresh snapshot; HTTP SSE
cursors do not promise MCP replay. Revoke, unsubscribe, close, disconnect, and
shutdown release subscriptions and wake pending waits.

`wait_for_turn` uses atomic check/register/recheck against the publisher and SDK
state. Return `{contract_version, timed_out, reason, state: StateResponse}`.
Reasons are `turn_ready`, `finished`, `closed`, `recovery_required`, or `timed_out`.
Turn readiness requires settled playable state for the requested slot with
revision strictly greater than `after_revision`; terminal lifecycle wakes even
without a newer revision. Setup/startup continue waiting until readiness or the
deadline. Authorization loss returns an error immediately. Limit concurrent waits
to 4 per caller and 64 per server; reject excess with an adapter `capacity_exceeded`
error. Waits never hold the mutation queue or reserve a turn. The agent host wakes,
reads, calls its model, and submits an action; the server schedules no model work.

## Images, archives, and payload bounds

`get_screenshot` requires the observed revision. Return a PNG MCP image content
block plus structured `{contract_version, match_id, revision, frame, mime_type}`.
Use only the committed image, enforce a 1 MiB PNG bound, and fail on unavailable
images or revision mismatch. Extend the SDK to retain/validate screenshot response
metadata and bind it to the observation; a race returns stale/unavailable rather
than mixing frames. Confirm image-block support with the pinned SDK before enabling.

Archive export returns structured `{contract_version, match_id, checkpoint_id,
mime_type: "application/zip", byte_length, sha256, archive_base64}`. Import decodes
strict base64 and sends raw bytes to SDK `import_checkpoint`; SDK/HTTP enforce
archive digest deduplication and store integrity/compatibility checks. Limit raw
archives to `MAX_ARCHIVE_BYTES` (4 MiB + 64 KiB), encoded data to
`4 * ceil(MAX_ARCHIVE_BYTES / 3)`, and the whole archive tool envelope to that bound
plus 64 KiB. Other tool argument envelopes retain the HTTP 64 KiB JSON limit and
shared path limit of 4,096 coordinates. Enforce bounds before decoding/allocation;
apply the same archive limit on export. Large-transfer tools must be capability
gated until host message limits are verified. Transfer by bytes and checkpoint ID
only; never accept or return server filesystem paths. Archives contain private
verifiers and save RAM and remain operator-only even when metadata is player-readable.

## Implementation and verification

The SDK-backed [tool implementation](MCP-TOOLS.md) includes bounded screenshot
metadata validation, debug wrappers, and revision-aware bounded turn waiting.
Protocol/SDK compatibility, authenticated sessions, resource subscriptions, and
application limits are implemented and covered by ROM-independent tests; see
[MCP-COMPATIBILITY.md](MCP-COMPATIBILITY.md) and the acceptance evidence in
[MILESTONE-4.org](MILESTONE-4.org). Live emulator play and interoperability with
third-party agent hosts remain unverified and are tracked separately.
