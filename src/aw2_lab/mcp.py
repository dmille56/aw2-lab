"""MCP server for AW2 Lab, mounted by the API server."""

from mcp.server.fastmcp import FastMCP

from aw2_lab import __version__

server = FastMCP(
    "aw2-lab",
    streamable_http_path="/",
    instructions=(
        "AW2 game contract version 1 is independent of MCP protocol negotiation. "
        "Only the greeting scaffold is currently exposed; gameplay and game resources "
        "are unavailable. Read /v1/capabilities for implemented features."
    ),
)
# FastMCP 1.29 has no constructor version argument. Set the underlying server's
# explicit implementation version so initialize does not report the MCP SDK version.
server._mcp_server.version = __version__


@server.tool()
def hello_world() -> str:
    """Return a greeting to confirm the AW2 Lab MCP server is available."""
    return "Hello, world!"
