# MCP SDK compatibility and version reporting

Milestone 4 audit of the repository's locked environment. This records library
support and ROM-independent implementation checks. Host-specific subscription
behavior and compatibility with a particular desktop or hosted agent client
remain unverified; see [the host guide](MCP-INTEGRATION.md).

## Reproducible baseline

`flake.lock` pins nixpkgs revision
`09063bd1f2b36fd9fd793c36dfade7bd40a93dfc`. Its
`python314Packages.mcp` resolves to **1.29.0**. `pyproject.toml` now requires
`mcp==1.29.0` so installations outside Nix use the audited SDK too. No flake input
update is needed. The SDK remains in its 1.x API family; current upstream main
may document a different major version. Use the versioned sources below when
implementing this adapter. A future dependency update must repeat this audit,
update the pin, and run the compatibility checks.

## Supported features and integration constraints

| Area | Evidence in SDK 1.29.0 | AW2 integration decision |
| --- | --- | --- |
| Protocol revisions | `shared/version.py` supports `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`; `types.LATEST_PROTOCOL_VERSION` is `2025-11-25` | Report this transport list independently of game contracts. SDK initialization selects a requested supported revision, otherwise offers its latest; the client must accept the negotiated result. This list alone does not promise every transport/feature exists in every revision. |
| Streamable HTTP | FastMCP supplies `streamable_http_app()` and a lifespan-managed session manager; transport validates protocol headers | Keep the mounted `/mcp` endpoint and existing application lifespan. HTTP SSE remains a separate application interface. |
| Authentication | FastMCP accepts `auth`, `token_verifier`, and `auth_server_provider`; auth middleware and `get_access_token()` expose request-scoped verified identity | The [local authorization boundary](MCP-AUTHORIZATION.md) validates shared bearer credentials, sessions/origins, and revocation, and supplies caller-specific SDK credentials. OAuth discovery and remote gameplay stay disabled. |
| Resource reads | FastMCP supports concrete resources and resource templates | AW2 exposes versioned state/command URIs with authorization on every read; see [MCP observations](MCP-OBSERVATIONS.md). |
| Resource subscriptions | Low-level `subscribe_resource()` / `unsubscribe_resource()` handlers and `ServerSession.send_resource_updated()` exist | AW2 implements authorized `resources/subscribe`, `resources/unsubscribe`, and `notifications/resources/updated`, including bounded per-session ownership and resynchronization invalidations. The adapter explicitly advertises subscriptions after installing the handlers. Host-specific behavior remains unverified. No additional newer subscription API is assumed. |
| Images | `Image(data=..., format="png")` and `types.ImageContent` support in-memory base64 content | Return bounded committed screenshots and revision/frame metadata, without filesystem paths. A synthetic round trip checks image content serialization, not image decoding or a real screenshot. |
| Structured results | Tool annotations produce `outputSchema`; `CallToolResult.structuredContent` supports structured metadata alongside image content | Shared models can supply typed results. Synthetic checks verify a model return, mixed image/metadata result, and rejection of application contract v2 before the probe tool executes. |
| Request bounds | FastMCP defaults `max_request_body_size` to 4,194,304 bytes | The planned base64 archive envelope exceeds this. Configure the future MCP transport's outer limit to the bounded archive envelope, with smaller per-tool limits before decoding. Do not enable archive tools until both server and host limits are verified. |
| Replay | Streamable HTTP accepts an optional event store; the adapter supplies none | Advertise no MCP replay guarantee. Reconnect reads authoritative state regardless of HTTP SSE replay support. |

Subscriptions use the SDK's resource operations across the audited revision
family; later revisions in this SDK do not introduce a replacement subscription
contract. Feature/protocol gating and notification routing must be checked with
actual supported hosts before changing availability flags. No host-specific
message size, subscription behavior, or credential configuration is verified yet.

## Explicit version boundaries

`GET /v1/capabilities` exposes:

- `supported_game_contract_versions: [1]`: AW2 payload semantics, unchanged by MCP
  protocol negotiation. Shared models reject unsupported versions and noninteger
  versions before service calls; future gameplay tools must use those models.
- `mcp_compatibility`: actual installed SDK version, SDK-supported protocol
  revisions, preferred revision, `/mcp` endpoint, and Streamable HTTP transport.
  These describe SDK compatibility, not enabled gameplay.
- `mcp_resources`, `mcp_subscriptions`, `http_sse`, and gameplay availability:
  independent feature reports. MCP resource reads/subscriptions are advertised
  separately from HTTP SSE and gameplay availability.

MCP `initialize.serverInfo.version` reports `aw2_lab.__version__`, not the MCP SDK
package version. FastMCP 1.29.0 has no constructor version argument; the adapter
sets the underlying low-level server's explicit version, guarded by a compatibility
check. Initialization instructions identify contract v1 and the SDK-backed tool
status. The library continues to negotiate MCP protocol versions itself.

Keep v1 tool names stable at `/mcp`; use
`aw2://v1/matches/{match}/state` and
`aw2://v1/matches/{match}/commands/{command}` for future resources. A breaking AW2
contract uses a separate endpoint such as `/mcp/v2` and corresponding resource
URIs, retaining v1 during migration. Decoder schemas and checkpoint manifest
schemas retain their own existing version fields. Tool/resource names remain
specified in [MCP-API-DESIGN.md](MCP-API-DESIGN.md); the later [tool implementation](MCP-TOOLS.md) enables the SDK-backed
lifecycle, gameplay, command, and checkpoint surface.

## Verification and sources

`tests/test_mcp_compatibility.py` exercises the pinned SDK over in-memory MCP
sessions. It checks typed output, image plus metadata content, application-version
rejection before tool execution, initialization implementation version, protocol
metadata, and the default false subscription advertisement. Capability model
checks confirm game resources/subscriptions stay unavailable. This is synthetic
SDK evidence; mounted authenticated HTTP sessions, resource delivery, and actual
agent hosts remain later milestone verification tasks.

The audit inspected the installed Nix package sources corresponding to these
versioned upstream files:

- [Supported protocol revisions](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/shared/version.py)
- [FastMCP configuration and transport/auth setup](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/server/fastmcp/server.py)
- [Low-level capabilities and resource handlers](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/server/lowlevel/server.py)
- [Session negotiation and resource notifications](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/server/session.py)
- [Request-scoped auth context](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/server/auth/middleware/auth_context.py)
- [Protocol content and result models](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/types.py)
