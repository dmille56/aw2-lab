"""MCP server for AW2 Lab, mounted by the API server."""

from typing import Any

from mcp import McpError, types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from aw2_lab import __version__
from aw2_lab.mcp_boundary import AW2MCP
from aw2_lab.mcp_notifications import register_notifications
from aw2_lab.mcp_runtime import MCPAdapterRuntime
from aw2_lab.mcp_tools import MCP_BODY_BYTES, register_tools


def create_mcp_server(adapter: MCPAdapterRuntime | None = None) -> FastMCP:
    """Each API application owns its transport sessions and identity bindings."""
    server = AW2MCP(
        "aw2-lab",
        max_request_body_size=MCP_BODY_BYTES,
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
            "Authenticated lifecycle, gameplay, and checkpoint tools use the shared HTTP API. "
            "Read capabilities for verified profiles and available actions. Mutations return receipts; "
            "inspect command completion before acting again. Invitations/join use trusted host setup."
        ),
    )
    # FastMCP 1.29 has no constructor version argument.
    server._mcp_server.version = __version__

    register_tools(server, adapter)
    register_notifications(server, adapter)
    call_handler = server._mcp_server.request_handlers[types.CallToolRequest]

    async def dispatch(request: Any) -> Any:
        if server._tool_manager.get_tool(request.params.name) is None:
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="Unknown tool"))
        return await call_handler(request)

    server._mcp_server.request_handlers[types.CallToolRequest] = dispatch

    server.streamable_http_app()
    # FastMCP 1.29 exposes this setting on its session manager, not its constructor.
    server.session_manager.session_idle_timeout = 1800
    return server
