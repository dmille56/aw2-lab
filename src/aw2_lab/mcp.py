"""MCP server for AW2 Lab, mounted by the API server."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.requests import Request

from aw2_lab import __version__
from aw2_lab.api_contract import CapabilitiesResponse
from aw2_lab.authorization import AuthorizationError
from aw2_lab.match_contract import ContractModel, ErrorCode
from aw2_lab.mcp_auth import caller_from_request
from aw2_lab.mcp_runtime import MCPAdapterRuntime


def create_mcp_server(adapter: MCPAdapterRuntime | None = None) -> FastMCP:
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
            "The authenticated get_capabilities tool uses the shared HTTP API. Gameplay and game resources "
            "are unavailable. Read /v1/capabilities for implemented features."
        ),
    )
    # FastMCP 1.29 has no constructor version argument.
    server._mcp_server.version = __version__

    @server.tool()
    async def get_capabilities(
        contract_version: Annotated[int, Field(strict=True)] = 1,
    ) -> CapabilitiesResponse:
        """Read server capabilities; game contract v1 is independent of MCP protocol."""
        ContractModel.model_validate({"contract_version": contract_version})
        request = server.get_context().request_context.request
        if not isinstance(request, Request):
            raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
        caller = caller_from_request(request)
        if adapter is None:
            raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
        async with adapter.sdk(caller) as client:
            return await client.capabilities()

    server.streamable_http_app()
    # FastMCP 1.29 exposes this setting on its session manager, not its constructor.
    server.session_manager.session_idle_timeout = 1800
    return server
