# MCP application lifetime

Each `create_app()` owns one `MCPAdapterRuntime` and one MCP server/session manager.
The adapter holds references to the application's existing controller, shared event
publisher, and authorized service provider. It creates no emulator, match state,
queue, checkpoint store, authorization ledger, or command journal.

Startup starts the emulator, recovers the existing match/runtime, and starts the
controller before entering the adapter and MCP session-manager lifetimes. A startup
failure closes the controller and emulator through the application's exit stack.
The adapter rejects work before startup and after shutdown with `runtime_unavailable`.
The application and SDK session manager are single-use; construct a fresh application
to restart, preserving the configured durable storage.

## SDK connections and operation cleanup

Tools obtain the private caller context from the current MCP request and use
`MCPAdapterRuntime.sdk(caller)`. The adapter creates a dedicated `AsyncAW2Client`
with that caller's immutable bearer credential and the application's configured API
origin. The SDK talks to the same HTTP v1 routes as external clients; shared services
continue to authorize reads, mutations, retries, and execution. A caller from another
authorization service is rejected. Credentials and API URLs are never tool arguments.

`create_app(api_base_url=...)` defaults to `http://127.0.0.1:43127`. The CLI supplies
its selected host/port, converting wildcard binds to connectable loopback addresses
(`0.0.0.0` to `127.0.0.1`, `::` to `::1`). Custom embedders must provide their actual
listening origin. URLs may not contain credentials, query strings, fragments, or
path prefixes. The CLI requires a fixed port from 1 through 65535 for SDK routing;
embedders using a dynamically allocated listening socket must resolve its port
before constructing the application. Request Host/forwarded headers cannot change
the adapter's destination.

`MCPAdapterRuntime.operation(caller)` leases pending adapter work under shared
revocation guards. It yields an `AsyncExitStack` for resource subscription cleanup
and wait cancellation callbacks. Subscription and wait operations use this owner
and retain their own delivery-time permission checks. The SDK lease
registers client closure on the same stack. Completion, exceptions, revocation, and
disconnect remove the lease and close its resources.

On shutdown the MCP session manager cancels its protocol handlers and transports.
The adapter rejects new work, cancels remaining operation scopes, and waits up to
five seconds for lease cleanup. Cleanup runs under a bounded cancellation shield,
so a disconnected client cannot interrupt client closure. A stalled cleanup reports
`MCP operation cleanup deadline expired`; an undrained adapter reports
`MCP adapter cleanup deadline expired`. Accepted mutations belong to the controller;
its existing bounded drain/recovery logic runs before the emulator stops.

Stateful MCP sessions expire after 1,800 seconds of inactivity. A request for an
expired session receives 404 from the SDK; the host must initialize a new session
and re-read authoritative state. Session IDs grant no permission, and revocation
still blocks every new request and delivery. HTTP SSE replay remains independent
of MCP session lifetime.

## First SDK-backed tool and coexistence

The greeting tool is retired. The authenticated `get_capabilities` tool validates
AW2 contract v1 before constructing an SDK client, then returns the shared
`CapabilitiesResponse` from HTTP. It works without a playable emulator boundary
and reports unavailable runtime actions through the existing capabilities model.
Connection failures use the SDK's sanitized diagnostics; unsupported versions do
not make an HTTP call. Lifecycle, gameplay, command, checkpoint, observation,
debug, subscription, and turn-wait operations use this same owner. The
[integration guide](MCP-INTEGRATION.md) documents host connection and
responsibilities.

HTTP `/health`, `/v1` readiness/capabilities, HTTP SSE, and existing SDK clients
retain their routes and controller. Capabilities equality between MCP and HTTP
shows that MCP tools use the shared API and preserve its error/result contracts.

## Verification

`tests/test_mcp_runtime.py` uses the mounted MCP transport and an SDK client whose
transport points to the actual application through HTTPX ASGI transport. This
verifies HTTP routing and caller headers without a listening socket or ROM. It
checks MCP/HTTP capability equality while HTTP SSE delivers an initial state,
separate operator/player clients, version rejection before HTTP, client closure,
pending-operation cancellation, cleanup callbacks, idle-session expiry and fresh
initialization, startup failure, unavailable-runtime reporting, connection failure,
disconnect, bounded cleanup failure, and configured IPv4/IPv6 API origins.

These are ROM-independent lifecycle checks. Live gameplay and agent-host acceptance
remain later Milestone 4 tasks; no live emulator or remote host verification is
claimed here.
