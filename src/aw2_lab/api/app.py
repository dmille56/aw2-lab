"""HTTP and MCP application lifecycle and shared match-controller owner."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Protocol
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.types import ASGIApp

from aw2_lab.checkpoint import CheckpointError
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.command_journal import (
    CommandJournalEntry,
    JournalEvent,
    JsonlCommandJournal,
    new_journal_entry,
)
from aw2_lab.emulator import EmulatorLauncher, EmulatorSettings
from aw2_lab.match_checkpoint import CheckpointRuntime, CheckpointSession, MatchCheckpointService
from aw2_lab.match_contract import ErrorCode
from aw2_lab.match_controller import MatchController
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.mcp import server as mcp_server
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.state_decoder import capture_game_state
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
    checkpoint_store = CheckpointStore(durable_root / "checkpoints")
    journal = JsonlCommandJournal(durable_root / "commands.jsonl")
    controller = match_controller or MatchController(
        journal=journal,
        checkpoint_store=checkpoint_store,
    )
    rom_profile = select_rom_profile(settings.rom_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Run mGBA and the mounted MCP session manager for the server lifetime."""
        async with AsyncExitStack() as stack:
            await emulator_launcher.start()
            stack.push_async_callback(emulator_launcher.stop)
            if match_controller is None:
                service = await _recover_checkpoint_on_startup(
                    controller,
                    checkpoint_store,
                    journal,
                    emulator_launcher,
                    settings,
                    rom_profile.sha256,
                )
                application.state.match_checkpoint_service = service
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


async def _recover_checkpoint_on_startup(
    controller: MatchController,
    store: CheckpointStore,
    journal: JsonlCommandJournal,
    launcher: Launcher,
    settings: EmulatorSettings,
    rom_sha256: str,
) -> MatchCheckpointService | None:
    """Restore CURRENT or an interrupted command's pre-action state before queue start."""
    pointer = await asyncio.to_thread(store.current)
    journal_state = await journal.read_entries()
    grouped: dict[UUID, list[CommandJournalEntry]] = {}
    for entry in journal_state.entries:
        grouped.setdefault(entry.command_id, []).append(entry)
    if pointer is None and any(
        entry.event is JournalEvent.TERMINAL and entry.checkpoint_id is not None
        for entry in journal_state.entries
    ):
        raise CheckpointError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "The command journal references a committed checkpoint but CURRENT is missing",
        )
    unfinished = [
        events
        for events in grouped.values()
        if any(item.event is JournalEvent.RUNNING for item in events)
        and not any(item.event is JournalEvent.TERMINAL for item in events)
    ]
    if len(unfinished) > 1:
        raise RuntimeError("Command journal has multiple unfinished serialized commands")
    interrupted = (
        next((item for item in unfinished[0] if item.event is JournalEvent.RUNNING), None)
        if unfinished
        else None
    )

    checkpoint_id = pointer.checkpoint_id if pointer is not None else None
    if interrupted is not None and pointer is not None:
        committed = pointer.command_result
        if (
            committed is not None
            and committed.command_id == interrupted.command_id
            and committed.request_id == interrupted.request_id
        ):
            await journal.append(
                new_journal_entry(
                    event=JournalEvent.TERMINAL,
                    command_id=interrupted.command_id,
                    request_id=interrupted.request_id,
                    match_id=interrupted.match_id,
                    recovery_checkpoint_id=interrupted.recovery_checkpoint_id,
                    checkpoint_id=committed.checkpoint_id,
                    operation_name=interrupted.operation_name,
                    payload_fingerprint=interrupted.payload_fingerprint,
                    payload=interrupted.payload,
                    accepted_revision=interrupted.accepted_revision,
                    expected_revision=interrupted.expected_revision,
                    status=committed.status,
                    resulting_revision=committed.resulting_revision,
                    error=committed.error,
                )
            )
            interrupted = None
        elif interrupted.recovery_checkpoint_id is not None:
            checkpoint_id = interrupted.recovery_checkpoint_id
    elif interrupted is not None and interrupted.recovery_checkpoint_id is not None:
        checkpoint_id = interrupted.recovery_checkpoint_id

    if checkpoint_id is None:
        return None
    bridge = getattr(launcher, "bridge", None)
    build_identity = getattr(launcher, "build_identity", None)
    if bridge is None or build_identity is None:
        raise RuntimeError("A committed checkpoint exists but the launcher has no recovery bridge")
    manifest, _ = await asyncio.to_thread(store.load, checkpoint_id)
    if interrupted is not None and interrupted.match_id != manifest.match.match_id:
        raise CheckpointError(
            ErrorCode.CHECKPOINT_INCOMPATIBLE,
            "Unfinished command and recovery checkpoint belong to different matches",
        )
    match_entries = [
        entry for entry in journal_state.entries if entry.match_id == manifest.match.match_id
    ]
    durable_floor = max(
        [manifest.match.revision]
        + [entry.accepted_revision for entry in match_entries]
        + [entry.resulting_revision or 0 for entry in match_entries]
        + (
            [pointer.revision]
            if pointer is not None and pointer.match_id == manifest.match.match_id
            else []
        )
    )
    session = CheckpointSession(
        MatchObservationTracker(manifest.match.match_id),
        lambda: capture_game_state(bridge, rom_path=settings.rom_path),
    )
    service = MatchCheckpointService(
        controller=controller,
        store=store,
        bridge=bridge,
        session=session,
        runtime=CheckpointRuntime(
            rom_sha256=rom_sha256,
            emulator_build=build_identity,
            emulator_mode=settings.mode.value,
        ),
        journal=journal,
    )
    await service.restore_startup_checkpoint(
        checkpoint_id,
        durable_revision_floor=durable_floor,
        interrupted_command=interrupted,
    )
    return service
