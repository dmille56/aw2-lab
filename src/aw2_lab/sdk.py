"""Typed async HTTP client for game contract v1, independent of emulator internals."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from typing import Self, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from aw2_lab.api_contract import (
    CapabilitiesResponse,
    CheckpointListResponse,
    CheckpointResponse,
    CreateMatchRequest,
    GameplayCommandRequest,
    InvitationReference,
    JoinSlotResponse,
    MatchConfiguration,
    MatchListResponse,
    MatchSummary,
    ObservationResponse,
    ReadinessResponse,
    SlotAuthorization,
    StateResponse,
)
from aw2_lab.match_contract import (
    CheckpointReference,
    CommandReceipt,
    CommandResult,
    CommandStatus,
    ErrorResponse,
    GameplayAction,
    MatchLifecycle,
    PlayerSlot,
)
from aw2_lab.match_events import CommandUpdatedEvent, MatchEvent, MatchUpdatedEvent, SnapshotEvent

T = TypeVar("T", bound=BaseModel)
TERMINAL = frozenset(
    {
        CommandStatus.COMPLETED,
        CommandStatus.REJECTED,
        CommandStatus.ROLLED_BACK,
        CommandStatus.RECOVERY_REQUIRED,
    }
)
EVENT_ADAPTER: TypeAdapter[MatchEvent] = TypeAdapter(MatchEvent)


class SDKError(Exception):
    """Base client failure; messages never include credentials or response bodies."""


class APIError(SDKError):
    def __init__(self, status: int, response: ErrorResponse) -> None:
        super().__init__(f"API request failed: {status} {response.error.code.value}")
        self.status = status
        self.response = response


class TransportError(SDKError):
    def __init__(self, request_id: UUID | None) -> None:
        super().__init__("HTTP request failed; its server outcome may be unknown")
        self.request_id = request_id


class ProtocolError(SDKError):
    pass


class WaitTimeout(SDKError):
    """Only the local wait expired; accepted server work is not cancelled."""

    def __init__(self, match_id: UUID, command_id: UUID | None = None) -> None:
        super().__init__("Client wait expired; server work was not cancelled")
        self.match_id = match_id
        self.command_id = command_id


class AsyncAW2Client:
    """One credential per client. Use separate instances for operator and each player.

    Owns its HTTPX client and closes it on async context exit. Network retries reuse
    exactly the encoded body and request ID. Pass a request_id explicitly to resume
    an uncertain operation across client calls or process restarts.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:43127",
        *,
        credential: str | SecretStr | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = 2,
        retry_delay: float = 0.25,
    ) -> None:
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or url.userinfo or url.query or url.fragment:
            raise ValueError("Use an HTTP(S) base URL without credentials, query, or fragment")
        if not 0 <= retries <= 10 or not 0 < retry_delay <= 30:
            raise ValueError("Invalid bounded retry policy")
        token = credential.get_secret_value() if isinstance(credential, SecretStr) else credential
        if token is not None and (not 32 <= len(token) <= 128 or any(c.isspace() for c in token)):
            raise ValueError("Invalid bearer credential")
        self._http = httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(30),
        )
        self._retries = retries
        self._delay = retry_delay

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if not response.is_success:
            try:
                error = ErrorResponse.model_validate_json(response.content)
            except ValueError, ValidationError:
                raise ProtocolError(f"Non-contract HTTP error: {response.status_code}") from None
            raise APIError(response.status_code, error)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: object = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        request_id: UUID | None = None,
    ) -> httpx.Response:
        for attempt in range(self._retries + 1):
            try:
                response = await self._http.request(
                    method, path, json=payload, content=content, headers=headers
                )
            except httpx.TransportError:
                if attempt == self._retries:
                    raise TransportError(request_id) from None
            else:
                if response.status_code not in {429, 503} or attempt == self._retries:
                    self._check(response)
                    return response
            await asyncio.sleep(min(self._delay * 2**attempt, 30))
        raise AssertionError("Unreachable retry state")

    async def _json(
        self,
        model: type[T],
        method: str,
        path: str,
        *,
        payload: object = None,
        request_id: UUID | None = None,
    ) -> T:
        response = await self._request(method, path, payload=payload, request_id=request_id)
        try:
            return model.model_validate_json(response.content)
        except ValueError, ValidationError:
            raise ProtocolError("Invalid game contract response") from None

    @staticmethod
    def _path(match_id: UUID) -> str:
        return f"/v1/matches/{match_id}"

    async def capabilities(self) -> CapabilitiesResponse:
        return await self._json(CapabilitiesResponse, "GET", "/v1/capabilities")

    async def readiness(self) -> ReadinessResponse:
        return await self._json(ReadinessResponse, "GET", "/v1/readiness")

    async def create_match(
        self, configuration: MatchConfiguration | None = None, *, request_id: UUID | None = None
    ) -> MatchSummary:
        identifier = request_id or uuid4()
        body = (
            CreateMatchRequest(request_id=identifier)
            if configuration is None
            else CreateMatchRequest(request_id=identifier, configuration=configuration)
        )
        return await self._json(
            MatchSummary,
            "POST",
            "/v1/matches",
            payload=body.model_dump(
                mode="json", exclude={"configuration"} if configuration is None else set()
            ),
            request_id=identifier,
        )

    async def list_matches(self) -> MatchListResponse:
        return await self._json(MatchListResponse, "GET", "/v1/matches")

    async def inspect_match(self, match_id: UUID) -> MatchSummary:
        return await self._json(MatchSummary, "GET", self._path(match_id))

    async def invite(
        self,
        match_id: UUID,
        slot: PlayerSlot,
        invitation_token: SecretStr,
        *,
        expires_in_seconds: int = 900,
        request_id: UUID | None = None,
    ) -> InvitationReference:
        # Secret fields are excluded from shared model dumps, so encode them explicitly.
        from aw2_lab.api_contract import IssueInvitationRequest

        identifier = request_id or uuid4()
        body = IssueInvitationRequest(
            request_id=identifier,
            invitation_token=invitation_token,
            expires_in_seconds=expires_in_seconds,
        )
        payload = body.model_dump(mode="json")
        payload["invitation_token"] = invitation_token.get_secret_value()
        return await self._json(
            InvitationReference,
            "POST",
            self._path(match_id) + f"/slots/{slot.value}/invitations",
            payload=payload,
            request_id=identifier,
        )

    async def join(
        self,
        match_id: UUID,
        slot: PlayerSlot,
        invitation_token: SecretStr,
        display_name: str,
        *,
        request_id: UUID | None = None,
    ) -> JoinSlotResponse:
        from aw2_lab.api_contract import JoinSlotRequest

        identifier = request_id or uuid4()
        body = JoinSlotRequest(
            request_id=identifier, invitation_token=invitation_token, display_name=display_name
        )
        payload = body.model_dump(mode="json")
        payload["invitation_token"] = invitation_token.get_secret_value()
        return await self._json(
            JoinSlotResponse,
            "POST",
            self._path(match_id) + f"/slots/{slot.value}/join",
            payload=payload,
            request_id=identifier,
        )

    async def revoke(
        self, match_id: UUID, slot: PlayerSlot, *, request_id: UUID | None = None
    ) -> SlotAuthorization:
        identifier = request_id or uuid4()
        return await self._json(
            SlotAuthorization,
            "POST",
            self._path(match_id) + f"/slots/{slot.value}/revoke",
            payload={"request_id": str(identifier)},
            request_id=identifier,
        )

    async def _command(
        self, match_id: UUID, suffix: str, revision: int | None, *, request_id: UUID | None = None
    ) -> CommandReceipt:
        identifier = request_id or uuid4()
        body: dict[str, object] = {"request_id": str(identifier)}
        if revision is not None:
            body["expected_revision"] = revision
        return await self._json(
            CommandReceipt,
            "POST",
            self._path(match_id) + suffix,
            payload=body,
            request_id=identifier,
        )

    async def start(
        self, match_id: UUID, expected_revision: int, *, request_id: UUID | None = None
    ) -> CommandReceipt:
        return await self._command(match_id, "/start", expected_revision, request_id=request_id)

    async def close(self, match_id: UUID, *, request_id: UUID | None = None) -> CommandReceipt:
        return await self._command(match_id, "/close", None, request_id=request_id)

    async def state(self, match_id: UUID) -> StateResponse:
        return await self._json(StateResponse, "GET", self._path(match_id) + "/state")

    async def observation(self, match_id: UUID) -> ObservationResponse:
        return await self._json(ObservationResponse, "GET", self._path(match_id) + "/observation")

    async def screenshot(self, match_id: UUID, *, revision: int | None = None) -> bytes:
        suffix = "" if revision is None else f"?revision={revision}"
        response = await self._request("GET", self._path(match_id) + "/screenshot" + suffix)
        if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ProtocolError("Invalid screenshot response")
        return response.content

    async def submit(
        self,
        match_id: UUID,
        expected_revision: int,
        action: GameplayAction,
        *,
        request_id: UUID | None = None,
    ) -> CommandReceipt:
        identifier = request_id or uuid4()
        body = GameplayCommandRequest(
            request_id=identifier, expected_revision=expected_revision, action=action
        )
        return await self._json(
            CommandReceipt,
            "POST",
            self._path(match_id) + "/commands",
            payload=body.model_dump(mode="json"),
            request_id=identifier,
        )

    async def command_status(self, match_id: UUID, command_id: UUID) -> CommandResult:
        return await self._json(
            CommandResult, "GET", self._path(match_id) + f"/commands/{command_id}"
        )

    async def create_checkpoint(
        self, match_id: UUID, expected_revision: int, *, request_id: UUID | None = None
    ) -> CommandReceipt:
        return await self._command(
            match_id, "/checkpoints", expected_revision, request_id=request_id
        )

    async def list_checkpoints(self, match_id: UUID) -> CheckpointListResponse:
        return await self._json(
            CheckpointListResponse, "GET", self._path(match_id) + "/checkpoints"
        )

    async def inspect_checkpoint(self, match_id: UUID, checkpoint_id: UUID) -> CheckpointResponse:
        return await self._json(
            CheckpointResponse, "GET", self._path(match_id) + f"/checkpoints/{checkpoint_id}"
        )

    async def export_checkpoint(self, match_id: UUID, checkpoint_id: UUID) -> bytes:
        response = await self._request(
            "GET", self._path(match_id) + f"/checkpoints/{checkpoint_id}/archive"
        )
        return response.content

    async def import_checkpoint(
        self, match_id: UUID, archive: bytes, *, request_id: UUID | None = None
    ) -> CheckpointReference:
        from aw2_lab.checkpoint_store import MAX_ARCHIVE_BYTES

        if len(archive) > MAX_ARCHIVE_BYTES:
            raise ValueError("Archive exceeds upload limit")
        identifier = request_id or uuid4()
        response = await self._request(
            "POST",
            self._path(match_id) + "/checkpoints/import",
            content=archive,
            headers={"Content-Type": "application/zip", "Request-ID": str(identifier)},
            request_id=identifier,
        )
        try:
            return CheckpointReference.model_validate_json(response.content)
        except ValueError, ValidationError:
            raise ProtocolError("Invalid checkpoint response") from None

    async def restore_checkpoint(
        self,
        match_id: UUID,
        checkpoint_id: UUID,
        expected_revision: int,
        *,
        request_id: UUID | None = None,
    ) -> CommandReceipt:
        return await self._command(
            match_id,
            f"/checkpoints/{checkpoint_id}/restore",
            expected_revision,
            request_id=request_id,
        )

    async def events(
        self, match_id: UUID, *, last_event_id: str | None = None, reconnect: bool = True
    ) -> AsyncGenerator[MatchEvent]:
        """Yield validated events; snapshots replace state, resync requires command refresh.

        The cursor advances when iteration resumes after each yield. Persist an
        event's ID only after applying it. Cancel/close this iterator to disconnect.
        """
        if last_event_id is not None and (
            len(last_event_id) > 128 or "\n" in last_event_id or "\r" in last_event_id
        ):
            raise ValueError("Invalid event cursor")
        cursor = last_event_id
        seen: deque[str] = deque([cursor] if cursor else [], maxlen=256)
        closed = False
        failures = 0
        while True:
            try:
                async with self._http.stream(
                    "GET",
                    self._path(match_id) + "/events",
                    headers={"Last-Event-ID": cursor} if cursor else {},
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        self._check(response)
                    if (
                        response.headers.get("content-type", "").split(";")[0]
                        != "text/event-stream"
                    ):
                        raise ProtocolError("Expected an SSE stream")
                    data: list[str] = []
                    identifier = name = ""
                    size = 0
                    async for line in response.aiter_lines():
                        size += len(line.encode("utf-8"))
                        if size > 8 * 1024 * 1024:
                            raise ProtocolError("SSE event exceeds client limit")
                        if line == "":
                            if data:
                                try:
                                    event = EVENT_ADAPTER.validate_json("\n".join(data))
                                except ValueError, ValidationError:
                                    raise ProtocolError("Invalid event envelope") from None
                                if (
                                    event.match_id != match_id
                                    or event.event_id != identifier
                                    or event.event != name
                                ):
                                    raise ProtocolError("SSE framing disagrees with envelope")
                                if identifier not in seen:
                                    yield event
                                    cursor = identifier
                                    seen.append(identifier)
                                failures = 0
                                if (
                                    isinstance(event, (SnapshotEvent, MatchUpdatedEvent))
                                    and event.payload.summary.lifecycle is MatchLifecycle.CLOSED
                                ):
                                    closed = True
                            data, identifier, name, size = [], "", "", 0
                        elif not line.startswith(":"):
                            key, _, value = line.partition(":")
                            value = value.removeprefix(" ")
                            if key == "data":
                                data.append(value)
                            elif key == "id":
                                identifier = value
                            elif key == "event":
                                name = value
            except httpx.TransportError:
                if not reconnect:
                    raise TransportError(None) from None
            if closed or not reconnect:
                return
            if failures >= self._retries:
                raise TransportError(None)
            await asyncio.sleep(min(self._delay * 2**failures, 30))
            failures += 1

    async def wait_for_command(
        self, match_id: UUID, command_id: UUID, *, timeout: float = 30
    ) -> CommandResult:
        """Return terminal results including failures; timeout never cancels server work."""
        if timeout <= 0:
            raise ValueError("Wait timeout must be positive")
        try:
            async with asyncio.timeout(timeout):
                result = await self.command_status(match_id, command_id)
                if result.status in TERMINAL:
                    return result
                stream = self.events(match_id)
                try:
                    async for event in stream:
                        if (
                            isinstance(event, CommandUpdatedEvent)
                            and event.payload.command_id == command_id
                        ):
                            result = event.payload
                        elif isinstance(event, SnapshotEvent):
                            result = await self.command_status(match_id, command_id)
                        if result.status in TERMINAL:
                            return result
                finally:
                    await stream.aclose()
                result = await self.command_status(match_id, command_id)
                if result.status not in TERMINAL:
                    raise ProtocolError("Stream ended before command completion")
                return result
        except TimeoutError:
            raise WaitTimeout(match_id, command_id) from None

    async def wait_for_turn(
        self, match_id: UUID, slot: PlayerSlot, *, timeout: float = 300
    ) -> StateResponse:
        """Wake from SSE when a slot becomes active; hosts decide which action to take."""
        if timeout <= 0:
            raise ValueError("Wait timeout must be positive")
        try:
            async with asyncio.timeout(timeout):
                stream = self.events(match_id)
                try:
                    async for event in stream:
                        if isinstance(event, (SnapshotEvent, MatchUpdatedEvent)):
                            state = event.payload
                            if state.summary.lifecycle in {
                                MatchLifecycle.FINISHED,
                                MatchLifecycle.CLOSED,
                                MatchLifecycle.RECOVERY_REQUIRED,
                            }:
                                return state
                            observation = state.observation
                            battle = observation.game_state.battle.value if observation else None
                            if (
                                state.settled
                                and state.summary.lifecycle is MatchLifecycle.PLAYABLE
                                and battle
                                and battle.active_player_slot
                                == (1 if slot is PlayerSlot.SLOT_1 else 2)
                            ):
                                return state
                finally:
                    await stream.aclose()
                raise ProtocolError("Event stream ended without a turn boundary")
        except TimeoutError:
            raise WaitTimeout(match_id) from None
