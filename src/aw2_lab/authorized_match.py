"""Access-checked match entry points shared by future HTTP, SDK, and MCP adapters.

Adapters resolve bearer credentials to principals here, never from request fields.
The underlying controller's observation reads remain trusted internal primitives.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from uuid import UUID

from pydantic import SecretStr

from aw2_lab.api_contract import (
    CheckpointCompatibility,
    CheckpointResponse,
    CreateCheckpointRequest,
    CreateMatchRequest,
    GameplayCommandRequest,
    InvitationReference,
    IssueInvitationRequest,
    JoinSlotRequest,
    JoinSlotResponse,
    MatchSummary,
    Principal,
    RestoreCheckpointRequest,
    SlotAuthorization,
    StartMatchRequest,
    StateResponse,
    summary_from_controller,
)
from aw2_lab.authorization import AuthorizationError, AuthorizationService, Permission
from aw2_lab.checkpoint import CheckpointError
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.match_checkpoint import CheckpointRuntime, MatchCheckpointService
from aw2_lab.match_contract import (
    CheckpointReference,
    CommandReceipt,
    CommandRequest,
    CommandResult,
    ErrorCode,
    PlayerSlot,
)
from aw2_lab.match_controller import BoundaryScreenshot, MatchController
from aw2_lab.match_events import EventMessage, EventSubscription
from aw2_lab.match_observation import MatchObservation


class AuthorizedEventSubscription:
    """Recheck before every live/replay delivery, including heartbeat wakeups."""

    def __init__(
        self,
        subscription: EventSubscription,
        authorization: AuthorizationService,
        principal: Principal,
        match_id: UUID,
    ) -> None:
        self._subscription = subscription
        self._authorization = authorization
        self._principal = principal
        self._match_id = match_id
        self._unwatch = authorization.watch(principal, subscription.close)

    async def next(self, *, timeout: float = 15) -> EventMessage:
        self._authorization.authorize(self._principal, Permission.READ, self._match_id)
        try:
            async with asyncio.timeout(timeout):
                result = await self._subscription.next()
        except TimeoutError:
            self._authorization.authorize(self._principal, Permission.READ, self._match_id)
            raise
        self._authorization.authorize(self._principal, Permission.READ, self._match_id)
        return result

    def close(self) -> None:
        self._unwatch()
        self._subscription.close()


class AuthorizedMatchService:
    def __init__(
        self,
        controller: MatchController,
        *,
        checkpoint_store: CheckpointStore | None = None,
        checkpoint_provider: Callable[[], MatchCheckpointService | None] | None = None,
        checkpoint_identity_provider: Callable[[], CheckpointRuntime | None] | None = None,
    ) -> None:
        if controller.authorization is None:
            raise ValueError("Authorized match service requires an authorization ledger")
        self.controller = controller
        self.authorization: AuthorizationService = controller.authorization
        self._store = checkpoint_store
        self._checkpoint_provider = checkpoint_provider
        self._checkpoint_identity_provider = checkpoint_identity_provider

    def _checkpoint_identity(self) -> CheckpointRuntime | None:
        backend = self._checkpoint_provider() if self._checkpoint_provider else None
        if backend is not None:
            return backend.runtime
        return self._checkpoint_identity_provider() if self._checkpoint_identity_provider else None

    @property
    def checkpoint_import_available(self) -> bool:
        return self.checkpoint_reads_available and self._checkpoint_identity() is not None

    @property
    def checkpoints_available(self) -> bool:
        return self._checkpoint_provider is not None and self._checkpoint_provider() is not None

    @property
    def checkpoint_reads_available(self) -> bool:
        return self._store is not None or self.checkpoints_available

    def _checkpoints(
        self, principal: Principal, match_id: UUID, permission: Permission
    ) -> MatchCheckpointService:
        self.authorization.authorize(principal, permission, match_id)
        result = self._checkpoint_provider() if self._checkpoint_provider else None
        if result is None:
            raise AuthorizationError(
                ErrorCode.RUNTIME_UNAVAILABLE, "No initialized checkpoint runtime"
            )
        return result

    def _checkpoint_store(self) -> CheckpointStore:
        backend = self._checkpoint_provider() if self._checkpoint_provider else None
        result = backend.store if backend is not None else self._store
        if result is None:
            raise AuthorizationError(
                ErrorCode.RUNTIME_UNAVAILABLE, "Checkpoint storage is not configured"
            )
        return result

    async def create_checkpoint(
        self, principal: Principal, match_id: UUID, request: CreateCheckpointRequest
    ) -> CommandReceipt:
        backend = self._checkpoints(principal, match_id, Permission.CHECKPOINT_CREATE)
        return await backend.create(
            match_id,
            principal,
            request_id=request.request_id,
            expected_revision=request.expected_revision,
        )

    async def restore_checkpoint(
        self,
        principal: Principal,
        match_id: UUID,
        checkpoint_id: UUID,
        request: RestoreCheckpointRequest,
    ) -> CommandReceipt:
        backend = self._checkpoints(principal, match_id, Permission.ARCHIVE)
        return await backend.restore(
            match_id,
            checkpoint_id,
            principal,
            request_id=request.request_id,
            expected_revision=request.expected_revision,
        )

    async def import_checkpoint(
        self, principal: Principal, match_id: UUID, request_id: UUID, data: bytes
    ) -> CheckpointReference:
        self.authorization.authorize(principal, Permission.ARCHIVE, match_id)
        summary = await self.controller.inspect_match(match_id)
        store = self._checkpoint_store()
        identity = self._checkpoint_identity()

        def save() -> CheckpointReference:
            if identity is None:
                raise CheckpointError(
                    ErrorCode.RUNTIME_UNAVAILABLE,
                    "Checkpoint compatibility identity is unavailable",
                )
            manifest, state = MatchCheckpointService.validate_import(data, summary, identity)
            return store.save(manifest, state)

        return await self.controller.persist_checkpoint_import(
            principal, match_id, request_id, hashlib.sha256(data).hexdigest(), save
        )

    async def list_checkpoints(
        self, principal: Principal, match_id: UUID
    ) -> tuple[CheckpointReference, ...]:
        self.authorization.authorize(principal, Permission.READ, match_id)
        await self.controller.inspect_match(match_id)
        result = await asyncio.to_thread(self._checkpoint_store().list_references, match_id)
        self.authorization.authorize(principal, Permission.READ, match_id)
        return result

    async def inspect_checkpoint(
        self, principal: Principal, match_id: UUID, checkpoint_id: UUID
    ) -> CheckpointResponse:
        self.authorization.authorize(principal, Permission.READ, match_id)
        await self.controller.inspect_match(match_id)
        manifest, _ = await asyncio.to_thread(self._checkpoint_store().load, checkpoint_id)
        self.authorization.authorize(principal, Permission.READ, match_id)
        if manifest.match.match_id != match_id:
            raise CheckpointError(ErrorCode.CHECKPOINT_NOT_FOUND, "Checkpoint was not found")
        return CheckpointResponse(
            checkpoint=CheckpointReference(
                checkpoint_id=manifest.checkpoint_id,
                match_id=match_id,
                revision=manifest.match.revision,
                created_at=manifest.created_at,
            ),
            compatibility=CheckpointCompatibility(
                rom_sha256=manifest.rom_sha256,
                emulator_build=manifest.emulator_build,
                emulator_mode=manifest.emulator_mode,
                decoder_schema_version=manifest.decoder_schema_version,
                observation_schema_version=manifest.observation_schema_version,
            ),
        )

    async def export_checkpoint(
        self, principal: Principal, match_id: UUID, checkpoint_id: UUID
    ) -> bytes:
        self.authorization.authorize(principal, Permission.ARCHIVE, match_id)
        await self.inspect_checkpoint(principal, match_id, checkpoint_id)
        data = await asyncio.to_thread(self._checkpoint_store().export_archive, checkpoint_id)
        self.authorization.authorize(principal, Permission.ARCHIVE, match_id)
        return data

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

    async def subscribe_events(
        self, principal: Principal, match_id: UUID, *, cursor: str | None = None
    ) -> AuthorizedEventSubscription:
        self.authorization.authorize(principal, Permission.READ, match_id)
        subscription = await self.controller.subscribe_events(match_id, cursor=cursor)
        try:
            # watch() revalidates access after the await while registering the wakeup.
            return AuthorizedEventSubscription(
                subscription, self.authorization, principal, match_id
            )
        except BaseException:
            subscription.close()
            raise

    async def screenshot(
        self, principal: Principal, match_id: UUID, *, revision: int | None = None
    ) -> BoundaryScreenshot:
        self.authorization.authorize(principal, Permission.READ, match_id)
        result = await self.controller.current_screenshot(match_id, revision=revision)
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
