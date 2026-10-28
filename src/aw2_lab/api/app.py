"""HTTP and MCP application lifecycle and shared match-controller owner."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.types import ASGIApp

from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.command_journal import JsonlCommandJournal
from aw2_lab.emulator import EmulatorLauncher, EmulatorSettings
from aw2_lab.match_controller import MatchController
from aw2_lab.mcp import server as mcp_server
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.storage import resolve_storage_root


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
    match_controller: MatchController | None = None,
    storage_root: Path | None = None,
) -> FastAPI:
    """Create the API application and configure its emulator process."""
    emulator_launcher = launcher or EmulatorLauncher(settings)
    durable_root = resolve_storage_root(storage_root)
    controller = match_controller or MatchController(
        journal=JsonlCommandJournal(durable_root / "commands.jsonl")
    )
    checkpoint_store = CheckpointStore(durable_root / "checkpoints")
    rom_profile = select_rom_profile(settings.rom_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Run mGBA and the mounted MCP session manager for the server lifetime."""
        async with AsyncExitStack() as stack:
            await emulator_launcher.start()
            stack.push_async_callback(emulator_launcher.stop)
            stack.push_async_callback(controller.stop)
            await controller.start()
            async with mcp_server.session_manager.run():
                yield

    application = FastAPI(title="AW2 Lab API", version="0.1.0", lifespan=lifespan)
    application.state.emulator_settings = settings
    application.state.emulator_launcher = emulator_launcher
    application.state.match_controller = controller
    application.state.storage_root = durable_root
    application.state.checkpoint_store = checkpoint_store
    application.state.rom_profile = rom_profile

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        """Report HTTP responsiveness and whether the emulator process is alive."""
        status = "running" if emulator_launcher.is_running else "not_running"
        return HealthResponse(emulator=status)

    application.mount("/mcp", mcp_app)
    return application
