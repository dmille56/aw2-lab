"""Typed SDK-backed MCP v1 lifecycle, gameplay, and checkpoint operations."""

import asyncio
import base64
import binascii
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from mcp import types
from mcp.server.fastmcp import FastMCP
from pydantic import Field, TypeAdapter
from starlette.requests import Request

from aw2_lab.api_contract import (
    CapabilitiesResponse,
    CheckpointListResponse,
    CheckpointResponse,
    DebugMemoryReadResponse,
    MatchConfiguration,
    MatchListResponse,
    MatchSummary,
    ObservationResponse,
    ReadinessResponse,
    SlotAuthorization,
    StateResponse,
)
from aw2_lab.authorization import AuthorizationError, Permission
from aw2_lab.checkpoint_store import MAX_ARCHIVE_BYTES
from aw2_lab.match_contract import (
    AttackAction,
    CargoDrop,
    CheckpointReference,
    CommandReceipt,
    CommandResult,
    ContractModel,
    Coordinate,
    DiveAction,
    EndTurnAction,
    ErrorCode,
    JoinAction,
    LoadAction,
    MoveAttackAction,
    MoveCaptureAction,
    MoveWaitAction,
    PlayerSlot,
    PurchaseAction,
    Revision,
    RiseAction,
    SiloLaunchAction,
    SupplyAction,
    SurrenderAction,
    UnloadAction,
)
from aw2_lab.match_contract import (
    Revision as MatchRevision,
)
from aw2_lab.match_events import CommandUpdatedEvent
from aw2_lab.mcp_auth import caller_from_request
from aw2_lab.mcp_contract import MCPFailure
from aw2_lab.mcp_runtime import MCPAdapterRuntime
from aw2_lab.mcp_turn_wait import TurnWaitResult
from aw2_lab.mcp_turn_wait import wait_for_turn as await_turn
from aw2_lab.sdk import TERMINAL, AsyncAW2Client

MAX_ARCHIVE_BASE64 = 4 * ((MAX_ARCHIVE_BYTES + 2) // 3)
MCP_BODY_BYTES = MAX_ARCHIVE_BASE64 + 65536
Path = Annotated[tuple[Coordinate, ...], Field(max_length=4096)]
Drops = Annotated[tuple[CargoDrop, ...], Field(min_length=1, max_length=2)]
UnitID = Annotated[str, Field(min_length=1)]
WaitSeconds = Annotated[float, Field(strict=True, gt=0, le=60, allow_inf_nan=False)]
DebugFrames = Annotated[int, Field(strict=True, ge=1, le=600)]
DebugAddress = Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]
DebugReadLength = Annotated[int, Field(strict=True, ge=1, le=4096)]
DebugButtons = Annotated[
    tuple[
        Literal["a", "b", "select", "start", "up", "down", "left", "right", "l", "r", "neutral"],
        ...,
    ],
    Field(min_length=1, max_length=10),
]
DebugWriteData = Annotated[str, Field(min_length=4, max_length=344)]


class CommandWaitResult(ContractModel):
    timed_out: bool
    command: CommandResult


class ArchiveResult(ContractModel):
    match_id: UUID
    checkpoint_id: UUID
    mime_type: str = "application/zip"
    byte_length: int
    sha256: str
    archive_base64: str


def register_tools(server: FastMCP, adapter: MCPAdapterRuntime | None) -> None:
    @asynccontextmanager
    async def client(
        permission: Permission = Permission.READ, match_id: UUID | None = None
    ) -> AsyncIterator[AsyncAW2Client]:
        request = server.get_context().request_context.request
        if not isinstance(request, Request):
            raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
        caller = caller_from_request(request)
        caller.check(permission, match_id)
        if adapter is None:
            raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
        async with adapter.sdk(caller) as sdk:
            yield sdk
            caller.check(permission, match_id)

    @server.tool()
    async def get_capabilities(contract_version: int = 1) -> CapabilitiesResponse:
        """Read current capabilities, supported profiles, action availability, and limits."""
        async with client() as sdk:
            return await sdk.capabilities()

    @server.tool()
    async def get_readiness(contract_version: int = 1) -> ReadinessResponse:
        """Operator: inspect readiness without advancing the emulator."""
        async with client(Permission.ADMIN) as sdk:
            return await sdk.readiness()

    @server.tool()
    async def create_match(
        request_id: UUID, configuration: MatchConfiguration | None = None, contract_version: int = 1
    ) -> MatchSummary:
        """Operator: create the verified fixed profile. Reuse request_id for identical retries."""
        async with client(Permission.ADMIN) as sdk:
            return await sdk.create_match(configuration, request_id=request_id)

    @server.tool()
    async def list_matches(contract_version: int = 1) -> MatchListResponse:
        """Operator: list matches visible to this server."""
        async with client(Permission.ADMIN) as sdk:
            return await sdk.list_matches()

    @server.tool()
    async def inspect_match(match_id: UUID, contract_version: int = 1) -> MatchSummary:
        """Inspect an authorized match summary and slot status."""
        async with client(Permission.READ, match_id) as sdk:
            return await sdk.inspect_match(match_id)

    @server.tool()
    async def revoke_slot(
        match_id: UUID, player_slot: PlayerSlot, request_id: UUID, contract_version: int = 1
    ) -> SlotAuthorization:
        """Operator: revoke a slot's current access. Identical retries retain their meaning."""
        async with client(Permission.ADMIN, match_id) as sdk:
            return await sdk.revoke(match_id, player_slot, request_id=request_id)

    @server.tool()
    async def start_match(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Operator: queue Start at expected_revision; inspect the receipt's command to completion."""
        async with client(Permission.ADMIN, match_id) as sdk:
            return await sdk.start(match_id, expected_revision, request_id=request_id)

    @server.tool()
    async def close_match(
        match_id: UUID, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Operator: queue Close. Acceptance is not completion; reconcile through get_command."""
        async with client(Permission.ADMIN, match_id) as sdk:
            return await sdk.close(match_id, request_id=request_id)

    @server.tool()
    async def get_state(match_id: UUID, contract_version: int = 1) -> StateResponse:
        """Read settled/readiness state and explicit unknown fields without advancing frames."""
        async with client(Permission.READ, match_id) as sdk:
            return await sdk.state(match_id)

    @server.tool()
    async def get_observation(match_id: UUID, contract_version: int = 1) -> ObservationResponse:
        """Read the versioned game observation, including unavailable decoder fields."""
        async with client(Permission.READ, match_id) as sdk:
            return await sdk.observation(match_id)

    @server.tool(structured_output=False)
    async def get_screenshot(
        match_id: UUID, revision: MatchRevision, contract_version: int = 1
    ) -> types.CallToolResult:
        """Read the cached committed PNG for exactly this revision; executing frames are unavailable."""
        async with client(Permission.READ, match_id) as sdk:
            screenshot = await sdk.screenshot(match_id, revision=revision)
            metadata = {
                "contract_version": 1,
                "match_id": str(screenshot.match_id),
                "revision": screenshot.revision,
                "frame": screenshot.frame,
                "mime_type": screenshot.mime_type,
            }
            return types.CallToolResult(
                content=[
                    types.ImageContent(
                        type="image",
                        data=base64.b64encode(screenshot.png).decode("ascii"),
                        mimeType=screenshot.mime_type,
                    )
                ],
                structuredContent=metadata,
            )

    @server.tool()
    async def get_command(
        match_id: UUID, command_id: UUID, contract_version: int = 1
    ) -> CommandResult:
        """Read queued/running or terminal command status. A terminal error remains part of this result."""
        async with client(Permission.READ, match_id) as sdk:
            return await sdk.command_status(match_id, command_id)

    @server.tool()
    async def wait_for_command(
        match_id: UUID,
        command_id: UUID,
        timeout_seconds: WaitSeconds = 30,
        contract_version: int = 1,
    ) -> CommandWaitResult:
        """Wait at most 60 seconds for completion; timeout or cancellation never cancels accepted work."""
        request = server.get_context().request_context.request
        if not isinstance(request, Request):
            raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
        caller = caller_from_request(request)
        caller.check(Permission.READ, match_id)
        if adapter is None:
            raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
        matches = adapter.matches
        if matches is None:
            raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
        source = None
        try:
            async with adapter.sdk(caller) as sdk:
                async with asyncio.timeout(timeout_seconds):
                    try:
                        async with asyncio.timeout(timeout_seconds * 0.9):
                            source = await matches.subscribe_events(caller.principal, match_id)
                            while True:
                                command = await sdk.command_status(match_id, command_id)
                                if command.status in TERMINAL:
                                    return CommandWaitResult(timed_out=False, command=command)
                                try:
                                    message = await source.next(timeout=timeout_seconds)
                                except TimeoutError:
                                    continue
                                except StopAsyncIteration:
                                    source.close()
                                    source = await matches.subscribe_events(
                                        caller.principal, match_id
                                    )
                                    continue
                                event = message.event
                                if (
                                    isinstance(event, CommandUpdatedEvent)
                                    and event.payload.command_id == command_id
                                    and event.payload.status in TERMINAL
                                ):
                                    return CommandWaitResult(timed_out=False, command=event.payload)
                    except TimeoutError:
                        command = await sdk.command_status(match_id, command_id)
                        caller.check(Permission.READ, match_id)
                        return CommandWaitResult(
                            timed_out=command.status not in TERMINAL, command=command
                        )
        finally:
            if source is not None:
                source.close()

    @server.tool()
    async def wait_for_turn(
        match_id: UUID,
        player_slot: PlayerSlot,
        after_revision: Revision,
        timeout_seconds: WaitSeconds = 30,
        contract_version: int = 1,
    ) -> TurnWaitResult:
        """Wait up to 60 seconds for a newer ready turn or terminal state. Players wait for their own slot; operators may monitor either. The host chooses actions; waiting reserves no turn."""
        request = server.get_context().request_context.request
        if not isinstance(request, Request):
            raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
        caller = caller_from_request(request)
        if adapter is None:
            raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
        async with adapter.sdk(caller) as sdk:
            return await await_turn(
                adapter, caller, sdk, match_id, player_slot, after_revision, timeout_seconds
            )

    @server.tool()
    async def move_wait(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move then Wait. Path lists successive zero-based destination tiles, excluding the start."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                MoveWaitAction(unit_id=unit_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def move_attack(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        target: Coordinate,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move then attack a zero-based target. Indirect units require an empty path; direct units may move."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                MoveAttackAction(unit_id=unit_id, path=path, target=target),
                request_id=request_id,
            )

    @server.tool()
    async def attack(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        target: Coordinate,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Attack a zero-based target from the unit's current tile, including with indirect units."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                AttackAction(unit_id=unit_id, target=target),
                request_id=request_id,
            )

    @server.tool()
    async def move_capture(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move then capture with a capable unit. Empty path captures at its current position."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                MoveCaptureAction(unit_id=unit_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def join(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move onto an allied unit of the same type and Join it. The final path tile names the partner."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                JoinAction(unit_id=unit_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def supply(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move an APC and supply every adjacent allied unit."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                SupplyAction(unit_id=unit_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def dive(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move a surfaced Sub, then Dive."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                DiveAction(unit_id=unit_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def rise(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move a submerged Sub, then Rise."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                RiseAction(unit_id=unit_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def silo_launch(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        path: Path,
        target: Coordinate,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move an Infantry/Mech onto a missile silo and launch at a target."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                SiloLaunchAction(unit_id=unit_id, path=path, target=target),
                request_id=request_id,
            )

    @server.tool()
    async def load(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        unit_id: UnitID,
        transport_id: UnitID,
        path: Path,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move a compatible unit to an allied transport and load it."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                LoadAction(unit_id=unit_id, transport_id=transport_id, path=path),
                request_id=request_id,
            )

    @server.tool()
    async def unload(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        transport_id: UnitID,
        path: Path,
        drops: Drops,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Move an allied transport, then drop its named cargo units at map coordinates."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                UnloadAction(transport_id=transport_id, path=path, drops=drops),
                request_id=request_id,
            )

    @server.tool()
    async def purchase(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        property: Coordinate,
        unit_type: UnitID,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Purchase an advertised unit type at an owned production property's zero-based coordinate."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id,
                expected_revision,
                PurchaseAction(property=property, unit_type=unit_type),
                request_id=request_id,
            )

    @server.tool()
    async def activate_normal_power(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Request normal CO Power activation for the caller's active turn."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.activate_normal_power(
                match_id, expected_revision, request_id=request_id
            )

    @server.tool()
    async def activate_super_power(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Request Super CO Power activation for the caller's active turn."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.activate_super_power(
                match_id, expected_revision, request_id=request_id
            )

    @server.tool()
    async def end_turn(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """End the caller's active turn at expected_revision. Wait for terminal command status."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id, expected_revision, EndTurnAction(), request_id=request_id
            )

    @server.tool()
    async def surrender(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Surrender the caller's active slot. This queues an irreversible gameplay decision."""
        async with client(Permission.PLAY, match_id) as sdk:
            return await sdk.submit(
                match_id, expected_revision, SurrenderAction(), request_id=request_id
            )

    @server.tool()
    async def create_checkpoint(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Queue a checkpoint at the expected revision; terminal result contains checkpoint_id."""
        async with client(Permission.CHECKPOINT_CREATE, match_id) as sdk:
            return await sdk.create_checkpoint(match_id, expected_revision, request_id=request_id)

    @server.tool()
    async def list_checkpoints(match_id: UUID, contract_version: int = 1) -> CheckpointListResponse:
        """List safe checkpoint references for this authorized match."""
        async with client(Permission.READ, match_id) as sdk:
            return await sdk.list_checkpoints(match_id)

    @server.tool()
    async def inspect_checkpoint(
        match_id: UUID, checkpoint_id: UUID, contract_version: int = 1
    ) -> CheckpointResponse:
        """Read safe checkpoint compatibility metadata, excluding paths and credential verifiers."""
        async with client(Permission.READ, match_id) as sdk:
            return await sdk.inspect_checkpoint(match_id, checkpoint_id)

    @server.tool()
    async def export_checkpoint(
        match_id: UUID, checkpoint_id: UUID, contract_version: int = 1
    ) -> ArchiveResult:
        """Operator: export a bounded ZIP as base64. Archives contain private verifiers/save RAM."""
        async with client(Permission.ARCHIVE, match_id) as sdk:
            archive = await sdk.export_checkpoint(match_id, checkpoint_id)
            if not archive or len(archive) > MAX_ARCHIVE_BYTES:
                raise ValueError("Invalid archive size")
            return ArchiveResult(
                match_id=match_id,
                checkpoint_id=checkpoint_id,
                byte_length=len(archive),
                sha256=hashlib.sha256(archive).hexdigest(),
                archive_base64=base64.b64encode(archive).decode("ascii"),
            )

    @server.tool()
    async def import_checkpoint(
        match_id: UUID,
        request_id: UUID,
        archive_base64: Annotated[str, Field(min_length=4, max_length=MAX_ARCHIVE_BASE64)],
        contract_version: int = 1,
    ) -> CheckpointReference:
        """Operator: import strict base64 ZIP bytes. Reuse request_id and identical bytes on retries."""
        async with client(Permission.ARCHIVE, match_id) as sdk:
            try:
                archive = base64.b64decode(archive_base64, validate=True)
            except binascii.Error, ValueError:
                raise ValueError("Invalid base64 archive") from None
            if not archive or len(archive) > MAX_ARCHIVE_BYTES:
                raise ValueError("Invalid archive size")
            return await sdk.import_checkpoint(match_id, archive, request_id=request_id)

    @server.tool()
    async def restore_checkpoint(
        match_id: UUID,
        checkpoint_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Operator: queue compatible checkpoint restoration at expected_revision; never restores revoked access."""
        async with client(Permission.ARCHIVE, match_id) as sdk:
            return await sdk.restore_checkpoint(
                match_id, checkpoint_id, expected_revision, request_id=request_id
            )

    @server.resource("aw2://v1/matches/{match_id}/state", mime_type="application/json")
    async def match_state_resource(match_id: str) -> str:
        """Authorized, committed match state; read-only and safe to refresh after reconnect."""
        identifier = UUID(match_id)
        async with client(Permission.READ, identifier) as sdk:
            state = await sdk.state(identifier)
            return state.model_dump_json()

    @server.resource(
        "aw2://v1/matches/{match_id}/commands/{command_id}", mime_type="application/json"
    )
    async def command_status_resource(match_id: str, command_id: str) -> str:
        """Authorized command status and terminal error, independent of tool-call history."""
        match, command = UUID(match_id), UUID(command_id)
        async with client(Permission.READ, match) as sdk:
            status = await sdk.command_status(match, command)
            return status.model_dump_json()

    @server.tool()
    async def debug_press_buttons(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        buttons: DebugButtons,
        frames: DebugFrames,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Operator debug: press named buttons for 1–600 frames. Changes invalidate game identity; restore before gameplay."""
        async with client(Permission.DEBUG, match_id) as sdk:
            return await sdk.debug_buttons(
                match_id, expected_revision, buttons, frames, request_id=request_id
            )

    @server.tool()
    async def debug_advance_frames(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        frames: DebugFrames,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Operator debug: advance 1–600 frames. The resulting boundary requires explicit restore before gameplay."""
        async with client(Permission.DEBUG, match_id) as sdk:
            return await sdk.debug_frames(
                match_id, expected_revision, frames, request_id=request_id
            )

    @server.tool()
    async def debug_read_memory(
        match_id: UUID,
        expected_revision: Revision,
        address: DebugAddress,
        length: DebugReadLength,
        contract_version: int = 1,
    ) -> DebugMemoryReadResponse:
        """Operator debug: read at most 4,096 bytes of EWRAM/IWRAM at a serialized, revision-checked boundary."""
        async with client(Permission.DEBUG, match_id) as sdk:
            return await sdk.debug_read_memory(match_id, expected_revision, address, length)

    @server.tool()
    async def debug_write_memory(
        match_id: UUID,
        expected_revision: Revision,
        request_id: UUID,
        address: DebugAddress,
        data: DebugWriteData,
        contract_version: int = 1,
    ) -> CommandReceipt:
        """Operator debug: write 1–256 canonical-base64 bytes within EWRAM/IWRAM. Restore before gameplay resumes."""
        async with client(Permission.DEBUG, match_id) as sdk:
            return await sdk.debug_write_memory(
                match_id, expected_revision, address, data, request_id=request_id
            )

    @server.tool()
    async def debug_reset(
        match_id: UUID, expected_revision: Revision, request_id: UUID, contract_version: int = 1
    ) -> CommandReceipt:
        """Operator debug: reset the emulator. Game observation becomes unavailable; restore before gameplay resumes."""
        async with client(Permission.DEBUG, match_id) as sdk:
            return await sdk.debug_reset(match_id, expected_revision, request_id=request_id)

    for tool in server._tool_manager.list_tools():
        if tool.fn_metadata.output_model is not None:
            tool.fn_metadata.output_schema = TypeAdapter(
                tool.fn_metadata.output_model | MCPFailure
            ).json_schema()
            tool.fn_metadata.output_schema["type"] = "object"
        tool.parameters["additionalProperties"] = False
        tool.parameters["properties"]["contract_version"] = {
            "type": "integer",
            "const": 1,
            "default": 1,
        }
