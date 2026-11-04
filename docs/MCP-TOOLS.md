# MCP v1 lifecycle, gameplay, and checkpoint tools

The authenticated `/mcp` endpoint now exposes 22 typed tools through the existing
Python SDK and HTTP v1 services. Use the pinned Python MCP SDK 1.29.0 and local
bearer setup in [MCP-AUTHORIZATION.md](MCP-AUTHORIZATION.md). Discover schemas
through `tools/list`; each schema includes `contract_version: 1` and rejects
unknown arguments. Mutations require an explicit UUID `request_id`.

| Group | Tools | Access |
| --- | --- | --- |
| System | `get_capabilities`, `get_readiness` | Authenticated capabilities; operator readiness |
| Matches | `create_match`, `list_matches`, `inspect_match`, `revoke_slot`, `start_match`, `close_match` | Operator administration; joined player may inspect own match |
| Observations | `get_state`, `get_observation`, `get_screenshot`; state and command resources | Operator or joined player in own match |
| Commands | `get_command`, `wait_for_command` | Operator or joined player in own match |
| Gameplay | `move_wait`, `move_attack`, `move_capture`, `purchase`, `end_turn`, `surrender` | Player credential, own active slot |
| Checkpoints | `create_checkpoint`, `list_checkpoints`, `inspect_checkpoint` | Operator or joined player in own match |
| Transfers/recovery | `export_checkpoint`, `import_checkpoint`, `restore_checkpoint` | Operator only |

Invitation issuance and joining remain trusted host provisioning through SDK
`invite` and `join`. They do not appear in model-visible tool schemas, and their
secrets must stay outside prompts. Players cannot elevate privileges with a slot,
match ID, or supplied principal. The SDK's shared HTTP service rechecks authorization
and queued execution retains current ownership, turn, and revision checks.

## Inputs and command flow

`create_match` accepts the verified fixed Bean Island configuration, or omission
to resolve the existing default. Explicit `configuration: null` is rejected,
matching HTTP. Unsupported combinations use the existing API's stable error codes.
All tools reject unsupported application versions before SDK work; MCP protocol
negotiation remains independent.

Gameplay coordinates are zero-based. Paths explicitly list successive destination
tiles, excluding the starting tile. `unit_id` is an opaque tracked lifetime ID.
Stationary attacks use `move_attack` with an empty path; indirect units cannot
move then attack. Consult capabilities for available actions, unit types, and
runtime limitations. Schema validity does not imply a legal game action.

Start, Close, gameplay, checkpoint creation, and restore return `CommandReceipt`.
Acceptance is not success. Call `get_command` or `wait_for_command` with the
receipt's `command_id`, inspect the terminal status/error, and use the resulting
revision for the next action. Metadata create/revoke and archive import return
their shared results synchronously. These operations retain the HTTP queue,
checkpoint store, command journal, and authorization ledger; the adapter creates
no additional state or emulator.

`wait_for_command` defaults to 30 seconds and permits 0 < timeout_seconds <= 60.
It uses the SDK's SSE-backed completion helper, reserving the last 10% of its
budget for an authorized final status read. Return shape is
`{contract_version, timed_out, command}`. A final read that completes the command
returns `timed_out: false`; a still-running command returns `true`. If the entire
budget expires or the final read fails, return a structured error instead of an
invented command result. Cancellation or timeout never cancels accepted gameplay.

## Errors and retries

Successful structured content serializes the shared result model. Application
failures set MCP `isError: true` and return `MCPFailure` structured content:

```json
{
  "contract_version": 1,
  "error": {
    "contract_version": 1,
    "code": "stale_revision",
    "message": "...",
    "retryable": false,
    "details": {}
  },
  "http_status": 409
}
```

HTTP API error codes/messages and safe details are retained. Argument/version
errors return sanitized `invalid_request` without echoing inputs. A command-status
lookup is successful even when its terminal `CommandResult` is rejected, rolled
back, or recovery-required: that error belongs to the command result. Unknown
tool names return a JSON-RPC invalid-parameters error; malformed MCP envelopes
remain protocol errors. Tool output schemas describe both shared successes and
`MCPFailure` errors.

Adapter failures have separate `outcome_unknown`, `protocol_error`, and
`capacity_exceeded` codes; an expired wait uses shared `timeout`. Transport errors
include the original request ID when available. Never assume a failed HTTP response
means the mutation did not run. Retry using the same credential, request ID, and
exact payload. Changed data under an existing request ID conflicts. The adapter
never creates a replacement ID or cancels accepted controller work.

## Bounds and archives

At most four tool calls per principal and 64 across an application execute
concurrently; excess calls fail immediately with `capacity_exceeded`. Ordinary tool
arguments are bounded to 64 KiB and movement paths to 4,096 coordinates. Limits are
applied in the common boundary and shared typed models before SDK work.

Archive tools accept/return bytes as strict base64 and checkpoint UUIDs, never
server paths. Raw ZIP bytes are limited to `MAX_ARCHIVE_BYTES` (4 MiB + 64 KiB);
base64 is limited to `4 * ceil(MAX_ARCHIVE_BYTES / 3)`. The mounted transport permits
that encoded archive plus 64 KiB for its envelope. The SDK streams export reads
and stops at the raw bound (HTTP error bodies are capped at 64 KiB), closing the
response on failure. Import retains the store's member, decompression, digest,
compatibility, current-match, and durable deduplication checks.

Export returns `{contract_version, match_id, checkpoint_id, mime_type,
byte_length, sha256, archive_base64}`. Import returns `CheckpointReference` and
never restores the running match; explicit restore is queued. Exported archives
contain private authorization verifiers/save RAM and are operator-only, while
safe compatibility metadata remains readable by authorized players.

The pinned Python MCP client's maximum-size request/response path is checked
against the mounted Streamable HTTP endpoint using HTTPX ASGI transport. That
synthetic test uses a maximum-size export fixture and a deliberately corrupt
maximum-size upload to verify envelope handling. Other agent hosts may impose
smaller message limits; use a compatible trusted operator host for transfers.
No compatibility with another host is advertised by these checks.

## Verification and remaining scope

`tests/test_mcp_tools.py` exercises actual MCP initialization/tool calls, SDK/HTTP
routing, shared synthetic-runtime queue execution, all six gameplay mappings,
queued Start, durable retries and request-ID conflicts, lost-response retry,
checkpoint create/list/inspect/export/import/restore, revocation, validation,
capacity, waits, and Python MCP client transfer envelopes. SDK tests verify that
oversized archive streams stop reading and close. Gameplay executors are controlled
fixtures in these checks; this is not live emulator play evidence.

State/screenshot tools and resources, debug operations, resource notifications,
and `wait_for_turn` remain subsequent tasks. The broader authorization acceptance
check stays open until every delivered surface, including subscriptions, is covered.
Human/agent live play in both emulator modes remains later Milestone 4 verification.
