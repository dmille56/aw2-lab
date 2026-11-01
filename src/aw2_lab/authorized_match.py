"""Access-checked match entry points shared by future HTTP, SDK, and MCP adapters.

Adapters resolve bearer credentials to principals here, never from request fields.
The underlying controller's observation reads remain trusted internal primitives.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from pydantic import SecretStr

from aw2_lab.api_contract import (
    CreateMatchRequest,
    GameplayCommandRequest,
    InvitationReference,
    IssueInvitationRequest,
    JoinSlotRequest,
    JoinSlotResponse,
    MatchSummary,
    Principal,
    SlotAuthorization,
    StartMatchRequest,
    StateResponse,
    summary_from_controller,
)
from aw2_lab.authorization import AuthorizationError, AuthorizationService, Permission
from aw2_lab.match_contract import (
    CommandReceipt,
    CommandRequest,
    CommandResult,
    ErrorCode,
    PlayerSlot,
)
from aw2_lab.match_controller import MatchController
from aw2_lab.match_observation import MatchObservation


class AuthorizedMatchService:
    def __init__(self, controller: MatchController) -> None:
        if controller.authorization is None:
            raise ValueError("Authorized match service requires an authorization ledger")
        self.controller = controller
        self.authorization: AuthorizationService = controller.authorization

    def authenticate(self, credential: SecretStr) -> Principal:
        return self.authorization.authenticate(credential)

    async def create(self, principal: Principal, request: CreateMatchRequest) -> MatchSummary:
        return summary_from_controller(
            await self.controller.create_match(principal=principal, request=request)
        )

    async def invite(
        self,
        principal: Principal,
        match_id: UUID,
        slot: PlayerSlot,
        request: IssueInvitationRequest,
    ) -> InvitationReference:
        return await self.controller.issue_invitation(principal, match_id, slot, request)

    async def join(
        self, match_id: UUID, slot: PlayerSlot, credential: SecretStr, request: JoinSlotRequest
    ) -> JoinSlotResponse:
        principal = await self.controller.claim_slot(match_id, slot, credential, request)
        summary = await self.inspect(principal, match_id)
        return JoinSlotResponse(match=summary, player_slot=slot)

    async def revoke(
        self, principal: Principal, match_id: UUID, slot: PlayerSlot, request_id: UUID
    ) -> SlotAuthorization:
        return await self.controller.revoke_slot(principal, match_id, slot, request_id)

    async def inspect(self, principal: Principal, match_id: UUID) -> MatchSummary:
        self.authorization.authorize(principal, Permission.READ, match_id)
        result = await self.controller.inspect_match(match_id)
        self.authorization.authorize(principal, Permission.READ, match_id)
        return summary_from_controller(result)

    async def list_matches(self, principal: Principal) -> tuple[MatchSummary, ...]:
        self.authorization.authorize(principal, Permission.ADMIN)
        return tuple(
            [
                await self.inspect(principal, match.match_id)
                for match in self.authorization.summaries()
            ]
        )

    async def state(self, principal: Principal, match_id: UUID) -> StateResponse:
        self.authorization.authorize(principal, Permission.READ, match_id)
        result = await self.controller.current_state(match_id)
        self.authorization.authorize(principal, Permission.READ, match_id)
        return StateResponse(
            summary=summary_from_controller(result.summary),
            settled=result.settled,
            observation=result.observation,
        )

    async def observation(self, principal: Principal, match_id: UUID) -> MatchObservation:
        self.authorization.authorize(principal, Permission.READ, match_id)
        result = await self.controller.current_observation(match_id)
        self.authorization.authorize(principal, Permission.READ, match_id)
        return result

    async def start(
        self, principal: Principal, match_id: UUID, request: StartMatchRequest
    ) -> CommandReceipt:
        self.authorization.authorize(principal, Permission.ADMIN, match_id)
        return await self.controller.start_match(
            match_id,
            principal=principal,
            request_id=request.request_id,
            expected_revision=request.expected_revision,
        )

    async def close(self, principal: Principal, match_id: UUID, request_id: UUID) -> CommandReceipt:
        self.authorization.authorize(principal, Permission.ADMIN, match_id)
        return await self.controller.close_match(match_id, principal, request_id=request_id)

    async def submit(
        self, principal: Principal, match_id: UUID, request: GameplayCommandRequest
    ) -> CommandReceipt:
        self.authorization.authorize(principal, Permission.PLAY, match_id)
        if principal.kind != "player":
            raise AuthorizationError(
                ErrorCode.PERMISSION_DENIED, "Gameplay requires a player credential"
            )
        receipt = await self.controller.submit_command(
            CommandRequest(
                match_id=match_id,
                player_slot=principal.player_slot,
                # Executors still consume the legacy request shape; this is never a bearer token.
                credential=SecretStr("principal-mediated-command-placeholder"),
                request_id=request.request_id,
                expected_revision=request.expected_revision,
                action=request.action,
            ),
            principal=principal,
        )
        self.authorization.authorize(principal, Permission.PLAY, match_id)
        return receipt

    async def command_status(
        self, principal: Principal, match_id: UUID, command_id: UUID
    ) -> CommandResult:
        self.authorization.authorize(principal, Permission.READ, match_id)
        result = await self.controller.command_status(match_id, command_id)
        self.authorization.authorize(principal, Permission.READ, match_id)
        return result

    async def wait_for_command(
        self, principal: Principal, match_id: UUID, command_id: UUID, *, timeout: float
    ) -> CommandResult:
        self.authorization.authorize(principal, Permission.READ, match_id)
        revoked = asyncio.Event()
        unsubscribe = self.authorization.watch(principal, revoked.set)
        command = asyncio.create_task(
            self.controller.wait_for_command(match_id, command_id, timeout=timeout)
        )
        invalidated = asyncio.create_task(revoked.wait())
        try:
            await asyncio.wait({command, invalidated}, return_when=asyncio.FIRST_COMPLETED)
            self.authorization.authorize(principal, Permission.READ, match_id)
            return await command
        finally:
            unsubscribe()
            command.cancel()
            invalidated.cancel()
            await asyncio.gather(command, invalidated, return_exceptions=True)
