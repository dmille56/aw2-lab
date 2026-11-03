"""Operator debug operations serialized with gameplay and checkpoint restoration."""

import base64
from dataclasses import replace
from uuid import UUID, uuid4

from fastapi import APIRouter, Request

from aw2_lab.api_contract import (
    DebugButtonsRequest,
    DebugFramesRequest,
    DebugMemoryReadRequest,
    DebugMemoryReadResponse,
    DebugMemoryWriteRequest,
    DebugResetRequest,
    Principal,
)
from aw2_lab.authorization import AuthorizationError, Permission
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.bridge import MemorySnapshot
from aw2_lab.match_contract import (
    CommandReceipt,
    CommandStatus,
    ErrorBody,
    ErrorCode,
    MatchLifecycle,
)
from aw2_lab.match_controller import MatchControllerError, MutationOutcome
from aw2_lab.match_observation import ActionReadiness, IdentityStatus, MatchObservation
from aw2_lab.playable_runtime import PlayableRuntime
from aw2_lab.state_model import ObservedValue, ValueStatus

RAM_REGIONS = ((0x02000000, 0x02040000), (0x03000000, 0x03008000))
BUTTONS = {
    name: 1 << index
    for index, name in enumerate(
        ("a", "b", "select", "start", "right", "left", "up", "down", "r", "l")
    )
}
router = APIRouter(prefix="/v1/matches/{match_id}/debug", tags=["debug"])


def access(
    request: Request, match_id: UUID
) -> tuple[AuthorizedMatchService, Principal, PlayableRuntime]:
    from aw2_lab.api.v1 import service

    matches = service(request)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not 32 <= len(token) <= 128:
        raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "A bearer credential is required")
    from pydantic import SecretStr

    principal = matches.authenticate(SecretStr(token))
    matches.authorization.authorize(principal, Permission.DEBUG, match_id)
    runtime = request.app.state.playable_runtime
    if runtime is None:
        raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "Debug runtime is unavailable")
    return matches, principal, runtime


def require_ram(address: int, length: int) -> None:
    if not any(start <= address and address + length <= end for start, end in RAM_REGIONS):
        raise MatchControllerError(
            ErrorCode.INVALID_REQUEST, "Debug memory access requires work RAM"
        )


async def mutate(
    request: Request,
    match_id: UUID,
    body: DebugButtonsRequest | DebugFramesRequest | DebugMemoryWriteRequest | DebugResetRequest,
    operation: str,
) -> CommandReceipt:
    matches, principal, runtime = access(request, match_id)
    if isinstance(body, DebugMemoryWriteRequest):
        require_ram(body.address, len(base64.b64decode(body.data)))

    async def execute() -> MutationOutcome:
        service = runtime.checkpoints
        tracker = service.session.tracker
        if tracker.match_id != match_id:
            raise MatchControllerError(ErrorCode.OBSERVATION_UNAVAILABLE, "Runtime match mismatch")
        if isinstance(body, DebugButtonsRequest):
            mask = sum(BUTTONS.get(name, 0) for name in body.buttons)
            await runtime.bridge.press_keys(mask, body.frames)
        elif isinstance(body, DebugFramesRequest):
            await runtime.bridge.advance_frames(body.frames)
        elif isinstance(body, DebugResetRequest):
            await runtime.bridge.reset()
        else:
            data = base64.b64decode(body.data)
            result = await runtime.bridge.request(
                "write_memory", address=body.address, bytes=list(data)
            )
            if result.get("written") != len(data):
                raise RuntimeError("Debug memory write was not confirmed")
        await runtime.release_inputs()
        state = await service.session.capture_game_state()
        reason = "Debug mutation invalidated unit identity; restore a checkpoint before gameplay"
        state = replace(state, battle=ObservedValue(ValueStatus.UNAVAILABLE, None, (reason,)))
        observation = MatchObservation(
            match_id=match_id,
            revision=tracker.revision + 1,
            game_state=state,
            unit_identities=(),
            identity_status=IdentityStatus.UNAVAILABLE,
            identity_reasons=(reason,),
            action_readiness=ActionReadiness.UNKNOWN,
            action_readiness_reasons=(reason,),
        )
        tracker.mark_uncertain(reason)
        return MutationOutcome(
            observation=observation,
            lifecycle=MatchLifecycle.RECOVERY_REQUIRED,
            status=CommandStatus.RECOVERY_REQUIRED,
            error=ErrorBody(code=ErrorCode.RECOVERY_REQUIRED, message=reason),
        )

    return await matches.controller.submit_serialized_mutation(
        match_id=match_id,
        request_id=body.request_id,
        operation_name="debug_" + operation,
        payload=body,
        expected_revision=body.expected_revision,
        handler=execute,
        principal=principal,
    )


@router.post("/buttons", response_model=CommandReceipt, status_code=202)
async def buttons(request: Request, match_id: UUID, body: DebugButtonsRequest) -> CommandReceipt:
    return await mutate(request, match_id, body, "buttons")


@router.post("/frames", response_model=CommandReceipt, status_code=202)
async def frames(request: Request, match_id: UUID, body: DebugFramesRequest) -> CommandReceipt:
    return await mutate(request, match_id, body, "frames")


@router.post("/reset", response_model=CommandReceipt, status_code=202)
async def reset(request: Request, match_id: UUID, body: DebugResetRequest) -> CommandReceipt:
    return await mutate(request, match_id, body, "reset")


@router.post("/memory/write", response_model=CommandReceipt, status_code=202)
async def write(request: Request, match_id: UUID, body: DebugMemoryWriteRequest) -> CommandReceipt:
    return await mutate(request, match_id, body, "memory_write")


@router.post("/memory/read", response_model=DebugMemoryReadResponse)
async def read(
    request: Request, match_id: UUID, body: DebugMemoryReadRequest
) -> DebugMemoryReadResponse:
    matches, principal, runtime = access(request, match_id)
    require_ram(body.address, body.length)
    captured: list[MemorySnapshot] = []

    async def execute() -> MutationOutcome:
        summary = await matches.controller.inspect_match(match_id)
        if summary.lifecycle is not MatchLifecycle.PLAYABLE:
            raise MatchControllerError(
                ErrorCode.OBSERVATION_UNAVAILABLE, "Read requires a playable boundary"
            )
        snapshot = await runtime.bridge.read_memory_snapshot([(body.address, body.length)])
        observation = await matches.controller.current_observation(match_id)
        if snapshot.frame != observation.game_state.frame:
            raise MatchControllerError(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Debug read frame differs from the committed boundary",
            )
        captured.append(snapshot)
        return MutationOutcome(lifecycle=MatchLifecycle.PLAYABLE)

    receipt = await matches.controller.submit_serialized_mutation(
        match_id=match_id,
        request_id=uuid4(),
        operation_name="debug_memory_read",
        payload=body,
        expected_revision=body.expected_revision,
        handler=execute,
        principal=principal,
        mutates_emulator=False,
    )
    result = await matches.wait_for_command(principal, match_id, receipt.command_id, timeout=30)
    if result.status is not CommandStatus.COMPLETED:
        error = result.error or ErrorBody(
            code=ErrorCode.OBSERVATION_UNAVAILABLE, message="Read failed"
        )
        raise MatchControllerError(error.code, error.message)
    matches.authorization.authorize(principal, Permission.DEBUG, match_id)
    snapshot = captured[0]
    return DebugMemoryReadResponse(
        match_id=match_id,
        revision=body.expected_revision,
        frame=snapshot.frame,
        address=body.address,
        data=base64.b64encode(snapshot.ranges[0]).decode("ascii"),
    )
