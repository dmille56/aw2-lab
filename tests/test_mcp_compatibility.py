"""ROM-independent checks for the pinned SDK and version boundaries."""

import base64
from importlib.metadata import version

import pytest
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

from aw2_lab import __version__
from aw2_lab.api_contract import MCPCompatibility, Request
from aw2_lab.mcp import create_mcp_server


def test_mcp_version_reporting_without_adapter_disables_subscriptions() -> None:
    compatibility = MCPCompatibility()
    options = create_mcp_server()._mcp_server.create_initialization_options()
    assert compatibility.sdk_version == version("mcp") == "1.29.0"
    assert compatibility.supported_protocol_versions == tuple(SUPPORTED_PROTOCOL_VERSIONS)
    assert compatibility.preferred_protocol_version == types.LATEST_PROTOCOL_VERSION
    assert options.server_version == __version__
    assert options.capabilities.resources is not None
    assert options.capabilities.resources.subscribe is False


@pytest.mark.anyio
async def test_pinned_sdk_structured_validation_and_image_content() -> None:
    probe = FastMCP("compatibility-probe")
    calls = []

    @probe.tool()
    def validate_request(request: Request) -> Request:
        calls.append(request)
        return request

    @probe.tool()
    def image() -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.ImageContent(type="image", mimeType="image/png", data="cG5n")],
            structuredContent={"contract_version": 1, "revision": 0},
        )

    async with create_connected_server_and_client_session(probe) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert tools["validate_request"].outputSchema is not None
        payload = {"request_id": "00000000-0000-0000-0000-000000000001"}
        result = await session.call_tool("validate_request", {"request": payload})
        assert not result.isError
        assert result.structuredContent == {"contract_version": 1, **payload}
        result = await session.call_tool(
            "validate_request", {"request": {**payload, "contract_version": 2}}
        )
        assert result.isError
        assert len(calls) == 1
        result = await session.call_tool("image")
        assert result.structuredContent == {"contract_version": 1, "revision": 0}
        assert isinstance(result.content[0], types.ImageContent)
        assert base64.b64decode(result.content[0].data) == b"png"
