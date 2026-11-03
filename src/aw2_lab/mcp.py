"""MCP server for AW2 Lab, mounted by the API server."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request

from aw2_lab import __version__
from aw2_lab.authorization import AuthorizationError
from aw2_lab.match_contract import ErrorCode
from aw2_lab.mcp_auth import caller_from_request


def create_mcp_server() -> FastMCP:
    """Each API application owns its transport sessions and identity bindings."""
    server = FastMCP(
        "aw2-lab",
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1",
                "127.0.0.1:*",
                "localhost",
                "localhost:*",
                "[::1]",
                "[::1]:*",
            ],
            allowed_origins=[],
        ),
        instructions=(
            "AW2 game contract version 1 is independent of MCP protocol negotiation. "
            "Only an authenticated greeting is exposed. Gameplay and game resources "
            "are unavailable. Read /v1/capabilities for implemented features."
        ),
    )
    # FastMCP 1.29 has no constructor version argument.
    server._mcp_server.version = __version__

    @server.tool()
    def hello_world() -> str:
        """Confirm availability for the authenticated caller."""
        request = server.get_context().request_context.request
        if not isinstance(request, Request):
            raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
        caller_from_request(request)
        return "Hello, world!"

    return server


# Compatibility probe; application instances create their own server.
server = create_mcp_server()
