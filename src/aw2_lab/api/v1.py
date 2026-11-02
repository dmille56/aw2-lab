"""Authenticated v1 match lifecycle and observation HTTP adapters."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aw2_lab.api_contract import (
    MAX_JSON_BYTES,
    CapabilitiesResponse,
    CloseMatchRequest,
    CreateMatchRequest,
    FeatureAvailability,
    InvitationReference,
    IssueInvitationRequest,
    JoinSlotRequest,
    JoinSlotResponse,
    MatchListResponse,
    MatchSummary,
    ObservationResponse,
    Principal,
    RevokeSlotRequest,
    SlotAuthorization,
    StartMatchRequest,
    StateResponse,
)
from aw2_lab.api_validation import (
    ContractValidationError,
    HttpError,
    internal_error,
    map_error,
    validation_issues,
)
from aw2_lab.authorization import AuthorizationError
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.aw2_unit_profiles import UNIT_PROFILES
from aw2_lab.checkpoint import CheckpointError
from aw2_lab.command_journal import CommandJournalError
from aw2_lab.match_contract import (
    CommandReceipt,
    CommandResult,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    PlayerSlot,
)
from aw2_lab.match_controller import CommandRejected, MatchControllerError
from aw2_lab.ui_state import PRODUCTION_CHOICES


def error_response(error: HttpError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error.response.model_dump(mode="json"),
        headers=dict(error.headers),
    )


class BoundedV1Requests:
    """Bound JSON before FastAPI parses it and keep all protected responses uncached."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message["headers"] if k.lower() != b"cache-control"]
                message = {**message, "headers": headers + [(b"cache-control", b"no-store")]}
            await send(message)

        if scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, no_store)
            return
        content_type = dict(scope["headers"]).get(b"content-type", b"").split(b";", 1)[0]
        if content_type.strip().lower() != b"application/json":
            response = error_response(
                map_error(
                    ErrorBody(code=ErrorCode.INVALID_REQUEST, message="Expected application/json"),
                    request_failure_status=415,
                )
            )
            await response(scope, receive, no_store)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_JSON_BYTES:
                response = error_response(
                    map_error(
                        ErrorBody(
                            code=ErrorCode.INVALID_REQUEST, message="JSON body exceeds limit"
                        ),
                        request_failure_status=413,
                    )
                )
                await response(scope, receive, no_store)
                return
            if not message.get("more_body", False):
                break
        try:
            payload = json.loads(body)
        except ValueError, UnicodeError, RecursionError:
            response = error_response(
                map_error(
                    ErrorBody(code=ErrorCode.INVALID_REQUEST, message="Malformed JSON request"),
                    request_failure_status=400,
                )
            )
            await response(scope, receive, no_store)
            return
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        if isinstance(request_id, str):
            try:
                scope.setdefault("state", {})["request_id"] = UUID(request_id)
            except ValueError:
                pass
        consumed = False

        async def buffered_receive() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, no_store)


def service(request: Request) -> AuthorizedMatchService:
    result = request.app.state.authorized_matches
    if not isinstance(result, AuthorizedMatchService):
        raise AuthorizationError(
            ErrorCode.RUNTIME_UNAVAILABLE, "Operator provisioning is required for match access"
        )
    return result


bearer = HTTPBearer(auto_error=False)


def credential(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SecretStr:
    if credentials is None or not 32 <= len(credentials.credentials) <= 128:
        raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "A bearer credential is required")
    return SecretStr(credentials.credentials)


def authenticated(
    matches: Annotated[AuthorizedMatchService, Depends(service)],
    token: Annotated[SecretStr, Depends(credential)],
) -> Principal:
    return matches.authenticate(token)


Service = Annotated[AuthorizedMatchService, Depends(service)]
Caller = Annotated[Principal, Depends(authenticated)]
Credential = Annotated[SecretStr, Depends(credential)]
router = APIRouter(
    prefix="/v1",
    tags=["matches"],
    responses={
        status: {"model": ErrorResponse}
        for status in (400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503)
    },
)


@router.get("/capabilities", response_model=CapabilitiesResponse, tags=["system"])
async def capabilities(request: Request) -> CapabilitiesResponse:
    controller = request.app.state.match_controller
    configured = request.app.state.authorized_matches is not None

    def feature(name: str, implemented: bool, available: bool, reason: str) -> FeatureAvailability:
        return FeatureAvailability(
            name=name,
            implemented=implemented,
            available=available,
            verification="synthetic" if implemented else "unverified",
            unavailable_reason=None if available else reason,
        )

    operations = [
        feature(name, True, configured, "Operator provisioning is required")
        for name in (
            "create_match",
            "list_matches",
            "inspect_match",
            "issue_invitation",
            "revoke_slot",
            "join_slot",
            "close_match",
            "state",
            "observation",
            "command_status",
        )
    ]
    operations.extend(
        (
            feature(
                "start_match",
                True,
                configured and controller.runtime_available,
                "A configured, accepting playable runtime is required",
            ),
            feature(
                "screenshot",
                True,
                configured and controller.screenshots_configured,
                "Boundary screenshot capture is not configured",
            ),
        )
    )
    operations.extend(
        feature(name, False, False, "HTTP operation is not implemented")
        for name in ("readiness", "gameplay", "checkpoints", "debug")
    )
    return CapabilitiesResponse(
        operations=tuple(operations),
        actions=tuple(
            feature(name, True, False, "The gameplay HTTP route is not implemented")
            for name in (
                "move_wait",
                "move_attack",
                "move_capture",
                "purchase",
                "end_turn",
                "surrender",
            )
        ),
        production_unit_types=tuple(UNIT_PROFILES[kind].name for kind in PRODUCTION_CHOICES),
        http_sse=feature("http_sse", False, False, "SSE is not implemented"),
        mcp_subscriptions=feature(
            "mcp_subscriptions", False, False, "MCP subscriptions are not implemented"
        ),
    )


@router.post("/matches", response_model=MatchSummary, status_code=201)
async def create_match(
    body: CreateMatchRequest, response: Response, matches: Service, caller: Caller
) -> MatchSummary:
    summary = await matches.create(caller, body)
    response.headers["Location"] = f"/v1/matches/{summary.match_id}"
    return summary


@router.get("/matches", response_model=MatchListResponse)
async def list_matches(matches: Service, caller: Caller) -> MatchListResponse:
    return MatchListResponse(matches=await matches.list_matches(caller))


@router.get("/matches/{match_id}", response_model=MatchSummary)
async def inspect_match(match_id: UUID, matches: Service, caller: Caller) -> MatchSummary:
    return await matches.inspect(caller, match_id)


@router.post(
    "/matches/{match_id}/slots/{slot}/invitations",
    response_model=InvitationReference,
    status_code=201,
)
async def invite(
    match_id: UUID, slot: PlayerSlot, body: IssueInvitationRequest, matches: Service, caller: Caller
) -> InvitationReference:
    return await matches.invite(caller, match_id, slot, body)


@router.post("/matches/{match_id}/slots/{slot}/revoke", response_model=SlotAuthorization)
async def revoke(
    match_id: UUID, slot: PlayerSlot, body: RevokeSlotRequest, matches: Service, caller: Caller
) -> SlotAuthorization:
    return await matches.revoke(caller, match_id, slot, body.request_id)


@router.post("/matches/{match_id}/slots/{slot}/join", response_model=JoinSlotResponse)
async def join(
    match_id: UUID, slot: PlayerSlot, body: JoinSlotRequest, matches: Service, token: Credential
) -> JoinSlotResponse:
    return await matches.join(match_id, slot, token, body)


@router.post("/matches/{match_id}/start", response_model=CommandReceipt, status_code=202)
async def start(
    match_id: UUID, body: StartMatchRequest, matches: Service, caller: Caller
) -> CommandReceipt:
    return await matches.start(caller, match_id, body)


@router.post("/matches/{match_id}/close", response_model=CommandReceipt, status_code=202)
async def close(
    match_id: UUID, body: CloseMatchRequest, matches: Service, caller: Caller
) -> CommandReceipt:
    return await matches.close(caller, match_id, body.request_id)


@router.get("/matches/{match_id}/state", response_model=StateResponse)
async def state(match_id: UUID, matches: Service, caller: Caller) -> StateResponse:
    return await matches.state(caller, match_id)


@router.get("/matches/{match_id}/observation", response_model=ObservationResponse)
async def observation(match_id: UUID, matches: Service, caller: Caller) -> ObservationResponse:
    return ObservationResponse(observation=await matches.observation(caller, match_id))


@router.get(
    "/matches/{match_id}/screenshot",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def screenshot(
    match_id: UUID,
    matches: Service,
    caller: Caller,
    revision: Annotated[int | None, Query(ge=0, le=(1 << 53) - 1)] = None,
) -> Response:
    cached = await matches.screenshot(caller, match_id, revision=revision)
    return Response(
        content=cached.png,
        media_type="image/png",
        headers={
            "X-AW2-Match-ID": str(cached.match_id),
            "X-AW2-Revision": str(cached.revision),
            "X-AW2-Frame": str(cached.frame),
        },
    )


@router.get("/matches/{match_id}/commands/{command_id}", response_model=CommandResult)
async def command_status(
    match_id: UUID, command_id: UUID, matches: Service, caller: Caller
) -> CommandResult:
    return await matches.command_status(caller, match_id, command_id)


def install_v1(application: FastAPI) -> None:
    application.add_middleware(BoundedV1Requests)

    async def safe_error(request: Request, error: Exception) -> JSONResponse:
        if isinstance(
            error,
            (
                AuthorizationError,
                MatchControllerError,
                CommandRejected,
                CheckpointError,
                CommandJournalError,
                ContractValidationError,
            ),
        ):
            mapped = map_error(error.body, request_id=getattr(request.state, "request_id", None))
        else:
            mapped = internal_error(request_id=getattr(request.state, "request_id", None))
        return error_response(mapped)

    async def invalid_request(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        return error_response(
            validation_issues(
                error.errors(),
                request_id=getattr(request.state, "request_id", None),
            )
        )

    async def http_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, HTTPException)
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                request_id=getattr(request.state, "request_id", None),
                error=ErrorBody(
                    code=ErrorCode.INVALID_REQUEST, message="HTTP request is not supported"
                ),
            ).model_dump(mode="json"),
            headers={**(error.headers or {}), "Cache-Control": "no-store"},
        )

    for error_type in (
        AuthorizationError,
        MatchControllerError,
        CommandRejected,
        CheckpointError,
        CommandJournalError,
        ContractValidationError,
        Exception,
    ):
        application.add_exception_handler(error_type, safe_error)
    application.add_exception_handler(RequestValidationError, invalid_request)
    application.add_exception_handler(HTTPException, http_error)
    application.include_router(router)
