# Local MCP authorization

The mounted `/mcp` transport now requires the same operator or claimed-player
bearer credential as HTTP. Provision the operator through the existing private
secret file and claim player slots through the trusted HTTP/SDK setup flow in
[AUTHORIZATION.md](AUTHORIZATION.md). Credentials stay in host transport headers;
they are never tool arguments. No OAuth issuer/discovery or remote host integration
is introduced. The [SDK-backed tools](MCP-TOOLS.md) include lifecycle, gameplay,
command, checkpoint, state, screenshot, and opt-in debug operations. Authorized
resource subscriptions and bounded turn waiting are described in
[MCP-NOTIFICATIONS.md](MCP-NOTIFICATIONS.md) and
[MCP-TURN-WAIT.md](MCP-TURN-WAIT.md).

## Request and session enforcement

Each API application creates its own MCP server and session manager. Before
initialization, session reconnect, POST, GET, or DELETE reaches the SDK,
`MCPAuthorizationBoundary` authenticates its single bearer header through the
existing `AuthorizationService`. Missing/invalid/revoked credentials return a
sanitized 401 with `WWW-Authenticate: Bearer`; absent operator provisioning returns
503. Responses are `Cache-Control: no-store`. Authentication creates no matches,
invitations, claims, or operator tokens.

The middleware supplies the SDK's `AuthenticatedUser` with a private digest
identity derived from the credential and current principal generation. The pinned
SDK compares that identity with the session owner on every session request.
Another player or an operator cannot reuse that player's session ID; the SDK
returns 404. Revoking and reclaiming the same slot does not recover the old
session. Restart creates fresh session managers and reuses the durable shared
ledger, so checkpoint state and session identifiers cannot restore revoked access.

MCP currently accepts only loopback TCP peers. The SDK separately validates
loopback Host values (with or without ports), and rejects all Origin headers.
No browser origin or remote gameplay is enabled. Supplying forwarded headers
cannot bypass the peer check. Local SSH forwarding retains local bearer/session
requirements. Public deployment remains outside Milestone 4.

Every response chunk rechecks the captured principal through the shared service.
A revocation watcher wakes pending transport requests, stops stream delivery,
and is removed on completion or disconnect. If headers were already sent, close
the stream without sending further private content; otherwise return 401.
Accepted controller commands retain their existing execution and journal lifetime.
Transport cancellation never revokes or rolls back accepted commands by itself.
An unaffected caller's requests and sessions continue to work.

## Shared operation guards

`caller_from_request` obtains a private `MCPCaller` from the current protocol
request's ASGI scope, and rechecks authorization. Every tool and resource
handler obtains this context instead of trusting a model-supplied identity,
slot, or session ID; direct invocation without authenticated request context is
rejected.

`MCPCaller.check(permission, match_id)` uses the existing permission table:
operator administration and archive access, player reads/checkpoint creation for
its own match, player-only gameplay, and operator debug startup opt-in. A player
cannot elevate privileges by selecting another slot or match. Use it before
resource reads, cached receipts, subscription registration, and each delivery.

`MCPCaller.operation(permission, match_id)` additionally guards pending awaits,
registers a revocation wakeup, and rechecks permission before returning results.
It removes its watcher on completion, cancellation, or failure.
`MCPAdapterRuntime.sdk(caller)` supplies one dedicated SDK client with the
request's immutable credential inside a lifespan-owned guard and closes it on
exit. Its URL comes from application configuration, never from tool arguments.
See [MCP-LIFESPAN.md](MCP-LIFESPAN.md) for shutdown and SDK connection ownership. The HTTP
facade and queue keep their existing acceptance/execution-time checks for turn,
ownership, revision, permissions, and cached responses. The adapter owns no
alternative mutation path.

Lifecycle, gameplay, checkpoint, state, screenshot, debug, subscription, and
turn-wait operations use these guards. MCP resource subscriptions are bounded
invalidations, not replay; reconnect requires a fresh authorized read. The
Mounted operation and shared-service checks are linked in
[Milestone 4](MILESTONE-4.org); the full repository verification gate passes.
Third-party client reconnect and rendering behavior remains a separate
live-host check.

## Evidence

`tests/test_mcp_authorization.py` drives the actual Streamable HTTP app using
controlled local ASGI requests. It covers missing/invalid credentials, missing
provisioning, remote peers, Host/Origin rejection, initialization, cross-caller
session theft, revocation, unaffected caller sessions, secret-free discovery,
and shared permission checks through synthetic tools/resource handlers.
Additional checks cover active-stream termination, pending-operation wakeup,
watcher cleanup, denied operator gameplay, denied player administration/archive/debug,
cross-match reads, disabled debug, and direct unauthenticated tool calls.
These synthetic probe tools/resources are confined to tests.

The shared-service tests retain queue execution, cached-receipt,
checkpoint/restart, and revocation coverage. MCP gameplay uses controlled
emulator observations; live mGBA play, third-party agent-host behavior, and
remote authentication are not claimed by these ROM-independent checks.
