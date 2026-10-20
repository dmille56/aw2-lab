"""HTTP and MCP application; match and emulator operations come in later milestones."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.types import ASGIApp

from aw2_lab.mcp import server as mcp_server


class HealthResponse(BaseModel):
    status: str = "ok"
    emulator: str = "not_started"


mcp_app: ASGIApp = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the mounted MCP session manager for the lifetime of the API server."""
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="AW2 Lab API", version="0.1.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Report that the HTTP process is responsive; this does not imply a match is running."""
    return HealthResponse()


app.mount("/mcp", mcp_app)
