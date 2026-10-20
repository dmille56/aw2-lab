"""MCP server for AW2 Lab, mounted by the API server."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("aw2-lab", streamable_http_path="/")


@server.tool()
def hello_world() -> str:
    """Return a greeting to confirm the AW2 Lab MCP server is available."""
    return "Hello, world!"
