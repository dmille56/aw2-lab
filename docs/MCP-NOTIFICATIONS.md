# MCP resource notifications

The application advertises `resources.subscribe: true` when its shared MCP adapter
is installed. Subscribe to `aw2://v1/matches/{match_id}/state` or
`aw2://v1/matches/{match_id}/commands/{command_id}` using `resources/subscribe`.
Only existing, authorized command resources are accepted. Other URIs are rejected.
`resources/unsubscribe` is idempotent within the authenticated session.

Notifications use MCP `notifications/resources/updated` with a URI only. Read the
resource for current authoritative data. Notifications can be duplicated or
coalesced; they contain no game snapshot, credentials, HTTP event envelope, or SSE
replay cursor. An initial invalidation follows registration. State capture and
publisher registration share the controller lock, avoiding a missed-update gap.
Committed state and terminal command ordering follows the shared publisher;
separate HTTP requests to read resources may naturally observe newer boundaries.

There are at most 16 resource subscriptions per session and 64 per application.
Each uses the shared publisher's bounded count/byte buffer. Overflow triggers an
invalidation and fresh atomic publisher registration, so clients re-read state
rather than replaying dropped invalidations. Notification writes have a five-second
deadline; failed/blocked delivery releases the subscription. On reconnection,
always re-read authoritative state and explicitly subscribe again. This is not a
promise of transport replay.

Every registration and delivery checks current match access. Revocation wakes idle
subscriptions. Unsubscribe, match closure, session DELETE/idle expiry, and application
shutdown release publisher subscriptions and authorization watchers. Tasks belong
to the pinned SDK's session task group and the application adapter's operation
scope. A transient GET stream disconnect preserves the bounded MCP session;
reconnecting clients must resynchronize. Hosts should DELETE sessions when leaving
rather than treating a dropped stream as session termination. The existing session
idle timeout is 30 minutes.

Python MCP SDK 1.29.0 hardcodes the subscription capability to false. The adapter
registers standard Subscribe/Unsubscribe handlers and narrowly overrides the
instance capability result after installing those handlers. Unconfigured standalone
servers retain `subscribe: false`. No SDK files or global SDK behavior are changed.

`tests/test_mcp_notifications.py` covers the mounted protocol capability,
registration, actual SDK notification writes, session DELETE, state/command
filtering, initial invalidation, duplicate registration, wrong-match access,
revocation, capacity, overflow resynchronization, and session task cleanup using
controlled observations. These are ROM-independent checks. Real host rendering,
GET reconnect behavior, and live emulator parity remain in Milestone 4 acceptance
verification. The host still owns waking its model and choosing gameplay actions.
