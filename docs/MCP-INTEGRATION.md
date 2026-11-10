# Connecting MCP hosts and driving AW2 matches

This guide covers the implemented local MCP endpoint and the responsibilities
of the process hosting a human-facing or agent-facing client. It does not add a
built-in strategy, model scheduler, player, or remote authentication service.
The endpoint accepts loopback clients only.

## Start the server

Create the operator credential once, outside the checkout and Nix store, using
the private-file procedure in [AUTHORIZATION.md](AUTHORIZATION.md). Keep the
file mode private; do not paste its contents into a prompt, terminal transcript,
tracked configuration, or MCP tool argument. Start AW2 Lab from the project:

```sh
nix develop -c python -m aw2_lab \
  --rom /absolute/path/to/aw2.gba \
  --operator-secret-file ~/.config/aw2-lab/operator-token \
  --emulator-mode headless
```

Use `--emulator-mode windowed` when a visible mGBA window is needed. The server
defaults to `127.0.0.1:43127`; it mounts Streamable HTTP MCP at
`http://127.0.0.1:43127/mcp`. Windowed startup needs a working display and X
authorization in the environment that launches mGBA (including inside tmux).
Debug tools are hidden unless the server is started with `--enable-debug-api`.

The process uses one configured ROM, one emulator, one match controller, and
the selected durable storage directory. Use the existing
[HTTP setup flow](HTTP-API.md) or trusted SDK to create a match, issue private
slot invitations, and claim each slot before starting. The operator credential
does not grant gameplay permission. Generate a different high-entropy player
credential for each slot and deliver each only to that slot's host. Invitation
tokens are one-time setup secrets; player tokens are long-lived bearer
credentials. Keep both outside model prompts and tool schemas.

## Connect and negotiate

The audited server dependency is Python MCP SDK `1.29.0`. Its supported protocol
revisions and preferred revision are reported in
[MCP-COMPATIBILITY.md](MCP-COMPATIBILITY.md) and `/v1/capabilities` under
`mcp_compatibility`. This is the compatibility evidence for the server SDK;
AW2 Lab has not verified a separate desktop or hosted MCP client. Configure a
client for Streamable HTTP, endpoint `/mcp`, and an `Authorization: Bearer`
header containing the credential belonging to that client. Do not place a token
in the URL or request arguments. Local MCP rejects non-loopback peers and all
Origin headers; remote deployment and browser clients are unsupported.

MCP protocol negotiation is independent of the AW2 application contract. The
server advertises AW2 `contract_version: 1` on tool schemas/results and supports
`supported_game_contract_versions: [1]`. MCP protocol version comes from
`initialize`; AW2's breaking application contract would use a separately
versioned endpoint such as `/mcp/v2`. After initialization, call
`get_capabilities` and `tools/list`. Use the returned profile, action
availability, operation limits, and runtime status as authoritative. The only
advertised match profiles support 72 two-player built-in Versus maps, two external players, fog Off,
Clear weather, and the documented fixed rules. A valid tool schema does not
mean an action is legal in the current game state.

With the pinned Python SDK, a client session can be opened like this (load the
credential from a private file or secret manager; do not hardcode it in a
tracked host):

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def run_host(token: str) -> None:
    async with streamablehttp_client(
        "http://127.0.0.1:43127/mcp",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            capabilities = await session.call_tool("get_capabilities", {})
            tools = await session.list_tools()
            # Check structuredContent / isError before using returned values.
```

Treat the MCP server's advertised protocol and the host's own supported
features as separate checks. A client may call tools even if it cannot display
images or subscribe to resources.

## Human versus agent

For Pi 1.5.0, use the [local Pi host launcher](../examples/pi-host/README.md),
which isolates each player's MCP configuration and session history and exposes
only the AW2 tools. It supports connection checks without a model request.

An operator first provisions the match and gives a human player a private slot
credential through a trusted channel. The human UI connects to `/mcp` with that
player credential (or uses the existing HTTP/SDK client). A separate agent host
connects with the other player's credential. Neither host receives the
operator's token. The host loop is:

1. Read `get_state` and `get_observation`; optionally call `get_screenshot` for
   the exact committed revision. MCP resources are also available at
   `aw2://v1/matches/{match_id}/state` and
   `aw2://v1/matches/{match_id}/commands/{command_id}`.
2. When the match is started and the agent's slot is active at a settled ready
   boundary, choose an action in the host and submit the corresponding gameplay
   tool with the observed `revision`, a fresh UUID `request_id`, and the
   observation's opaque `unit_id` values.
3. Inspect the returned command receipt. A receipt means accepted, not
   completed. Call `wait_for_command` or `get_command` until terminal, inspect
   its status and error, then read state again before choosing another action.

For example, `move_wait` takes `match_id`, `expected_revision`, `request_id`,
`unit_id`, and `path`. Coordinates are zero-based; `path` lists each successive
destination and omits the starting tile. A successful move ends with Wait.
`attack` attacks from the current tile and supports indirect units.
`move_attack` can move then attack for direct units; its empty-path form remains
available, while indirect units cannot move then attack. `move_capture` moves
and captures; purchase and turn-end actions use their own typed tools. Follow
capabilities and current observation data; the server does not enumerate legal
moves or infer the host's strategy.

## Agent versus agent

Provision and start one match with the trusted operator flow, then configure two
independent agent-host processes. Give host A only player A's token and host B
only player B's token. Keep per-slot memory, model context, and secret storage
separate. Each host reads the shared authoritative match but can mutate only its
own active slot. The host checks the active slot and revision after each
notification or wait result, invokes its own model or policy, submits one
command, and follows that receipt to a terminal state. The two host processes
must not share a credential or assume that a notification schedules the other
host.

The same pattern works for deterministic test drivers, but that is not evidence
of model-host interoperability. Real human/agent and agent/agent runs in both
headless and windowed modes are tracked separately in
[Milestone 4](MILESTONE-4.org).

## Updates, reconnects, and waiting

Clients supporting MCP resource subscriptions may subscribe to the state URI
and, after receiving a receipt, that command's URI. An update notification is
an invalidation signal: read the resource to obtain current authoritative data.
Notifications can be duplicated, buffers are bounded, and MCP transport
replay is not promised. After reconnect, session expiry, subscription overflow,
or server restart, initialize/reconnect as appropriate, re-read state and
outstanding command status, then subscribe again. The server checks
authorization on resource reads and each delivery; revocation ends access.

Hosts without subscriptions should use `wait_for_turn(match_id, player_slot,
after_revision, timeout_seconds)` rather than repeatedly polling. The timeout
is bounded to 60 seconds. On `turn_ready`, use the returned current state and
revision; on `timed_out`, wait again or stop; on `finished`, `closed`, or
`recovery_required`, stop gameplay and handle that lifecycle. Waiting reserves
no turn and does not advance emulation. On a stale revision, re-read state and
make a new decision. After a client timeout or uncertain tool response, retry
the identical mutation with the same credential, request ID, and exact payload;
never generate a new request ID until the original outcome is known. A changed
payload under an existing ID conflicts. Cancellation or timeout does not undo
accepted work.

Configure the MCP HTTP client's response/read timeout to exceed the requested
`wait_for_command` or `wait_for_turn` timeout. Both MCP waits are capped at 60
seconds; a shorter transport timeout can close the response stream before the
tool's bounded wait returns.

## Recovery, images, and debug

Checkpoint creation is available to an authorized match participant or
operator; checkpoint archive export/import and restore require the operator.
Keep exported archives private because they include save data and authorization
verifiers. Restore is queued work: follow its receipt to completion and inspect
state again. Screenshots represent only a committed boundary and must be
requested for its exact revision. An unavailable screenshot is not permission
to inspect an executing frame.

Operator debug tools (`debug_press_buttons`, `debug_advance_frames`, bounded
memory access, and `debug_reset`) are exposed only when the server starts with
`--enable-debug-api`. They are for controlled diagnosis and can invalidate the
decoded gameplay boundary; follow the tool result's recovery guidance and
restore a compatible checkpoint before gameplay resumes. Do not expose the
operator token or debug control to an untrusted agent. See
[MCP tools](MCP-TOOLS.md), [notifications](MCP-NOTIFICATIONS.md), and
[turn waiting](MCP-TURN-WAIT.md) for detailed bounds and result semantics.

This guide documents the available integration surface. It does not claim
successful interoperability with an untested third-party host or live emulator
play. Record host/client versions, emulator mode, ROM/build identity, and
out-of-repository evidence when completing the live acceptance scenarios.
