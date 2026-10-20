"""HTTP and MCP application; match and emulator operations come in later milestones."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.types import ASGIApp

from aw2_lab.emulator import EmulatorLauncher, EmulatorSettings
from aw2_lab.mcp import server as mcp_server


class HealthResponse(BaseModel):
    status: str = "ok"
    emulator: str = "not_running"


mcp_app: ASGIApp = mcp_server.streamable_http_app()


class Launcher(Protocol):
    @property
    def is_running(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


def create_app(
    *,
    settings: EmulatorSettings,
    launcher: Launcher | None = None,
) -> FastAPI:
    """Create the API application and configure its emulator process."""
    emulator_launcher = launcher or EmulatorLauncher(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Run mGBA and the mounted MCP session manager for the server lifetime."""
        await emulator_launcher.start()
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            await emulator_launcher.stop()

    application = FastAPI(title="AW2 Lab API", version="0.1.0", lifespan=lifespan)
    application.state.emulator_settings = settings
    application.state.emulator_launcher = emulator_launcher

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        """Report HTTP responsiveness and whether the emulator process is alive."""
        status = "running" if emulator_launcher.is_running else "not_running"
        return HealthResponse(emulator=status)

    application.mount("/mcp", mcp_app)
    return application
