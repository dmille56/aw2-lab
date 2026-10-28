"""Single-match owner and bounded, idempotent mutation command queue."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, SecretStr

from aw2_lab.checkpoint import CheckpointError
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.command_journal import (
    CommandJournal,
    CommandJournalEntry,
    CommandJournalError,
    JournalEvent,
    new_journal_entry,
)
from aw2_lab.match_contract import (
    CommandReceipt,
    CommandRequest,
    CommandResult,
    CommandStatus,
    ErrorBody,
    ErrorCode,
    FixedMatchConfiguration,
    JoinSlotResponse,
    MatchLifecycle,
    MatchSummary,
    PlayerSlot,
    PlayerSlotState,
    SlotStatus,
)
from aw2_lab.match_observation import (
    ActionReadiness,
    MatchObservation,
)


class MatchControllerError(RuntimeError):
    """A safe public controller error with a stable machine-readable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, str | int | bool | None] | None = None,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            details=dict(details or {}),
        )


class CommandRejected(Exception):
    """Executor rejection known to have happened before any mutation."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, str | int | bool | None] | None = None,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(
            code=code, message=message, retryable=retryable, details=dict(details or {})
        )


@dataclass(frozen=True, slots=True)
class MutationOutcome:
    """Result returned by a serialized executor after it reaches a stable boundary."""

    observation: MatchObservation | None = None
    lifecycle: MatchLifecycle | None = None
    status: CommandStatus = CommandStatus.COMPLETED
    error: ErrorBody | None = None
    checkpoint_id: UUID | None = None
    commit_checkpoint: Callable[[CommandResult], Awaitable[None]] | None = None


@dataclass(frozen=True, slots=True)
class MatchStateSnapshot:
    """Atomically read match metadata and its last committed observation."""

    summary: MatchSummary
    observation: MatchObservation | None

    def __post_init__(self) -> None:
        if self.observation is not None and self.observation.revision != self.summary.revision:
            raise ValueError("Match summary and observation revisions must agree")

    @property
    def settled(self) -> bool:
        """Whether the snapshot is at a boundary where no mutation is running."""
        return self.summary.lifecycle is not MatchLifecycle.EXECUTING


class ActionExecutor(Protocol):
    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome: ...


MutationHandler = Callable[[], Awaitable[MutationOutcome]]
RecoveryCheckpointProvider = Callable[[UUID, UUID, int | None], Awaitable[UUID]]
RecoveryRollbackProvider = Callable[[UUID, UUID, UUID, ErrorBody], Awaitable[MutationOutcome]]
InputReleaseProvider = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class _MatchRecord:
    summary: MatchSummary
    credentials: dict[PlayerSlot, bytes] = field(default_factory=dict)
    observation: MatchObservation | None = None


@dataclass(slots=True)
class _CommandRecord:
    receipt: CommandReceipt
    payload_fingerprint: str
    request: CommandRequest | None = None
    handler: MutationHandler | None = None
    operation_name: str | None = None
    journal_payload: dict[str, Any] = field(default_factory=dict)
    expected_revision: int | None = None
    recovery_checkpoint_id: UUID | None = None
    mutates_emulator: bool = False
    allow_recovery: bool = False
    previous_lifecycle: MatchLifecycle | None = None
    result: CommandResult | None = None
    completed: asyncio.Event = field(default_factory=asyncio.Event)


class MatchController:
    """Own one active match and serialize every accepted mutation.

    Match setup, gameplay, debug, checkpoint, and restore integrations submit
    work through this queue. Emulator-specific navigation remains injected so
    this controller can be exercised using synthetic observations without a ROM.
    """

    def __init__(
        self,
        *,
        executor: ActionExecutor | None = None,
        journal: CommandJournal | None = None,
        recovery_checkpoint_provider: RecoveryCheckpointProvider | None = None,
        recovery_rollback_provider: RecoveryRollbackProvider | None = None,
        input_release_provider: InputReleaseProvider | None = None,
        checkpoint_store: CheckpointStore | None = None,
        queue_capacity: int = 64,
        command_capacity: int = 4096,
        shutdown_timeout: float = 30.0,
        shutdown_cancel_timeout: float = 1.0,
    ) -> None:
        if queue_capacity < 1 or command_capacity < queue_capacity:
            raise ValueError("Command capacities must be positive and history >= queue capacity")
        if shutdown_timeout <= 0 or shutdown_cancel_timeout <= 0:
            raise ValueError("Shutdown timeouts must be positive")
        self._executor = executor
        self._journal = journal
        self._recovery_checkpoint_provider = recovery_checkpoint_provider
        self._recovery_rollback_provider = recovery_rollback_provider
        self._input_release_provider = input_release_provider
        self._checkpoint_store = checkpoint_store
        self._queue: asyncio.Queue[_CommandRecord | None] = asyncio.Queue(queue_capacity)
        self._command_capacity = command_capacity
        self._shutdown_timeout = shutdown_timeout
        self._shutdown_cancel_timeout = shutdown_cancel_timeout
        self._matches: dict[UUID, _MatchRecord] = {}
        self._commands: dict[UUID, _CommandRecord] = {}
        self._requests: dict[UUID, _CommandRecord] = {}
        self._state_lock = asyncio.Lock()
        self._accept_lock = asyncio.Lock()
        self._worker: asyncio.Task[None] | None = None
        self._accepting = False
        self._stopped = False
        self._forced_shutdown = False
        self._journal_failed = False
        self._journal_diagnostic: ErrorBody | None = None
        self._running: _CommandRecord | None = None

    async def start(self) -> None:
        """Start the sole command worker; it remains alive while emulation is idle."""
        async with self._accept_lock:
            if self._stopped:
                raise RuntimeError("A stopped match controller cannot be restarted")
            if self._worker is not None:
                return
            await self._reconcile_durable_commands()
            self._accepting = not self._journal_failed
            self._worker = asyncio.create_task(self._run_queue(), name="aw2-match-command-queue")

    async def _reconcile_durable_commands(self) -> None:
        """Rebuild idempotency history and terminalize work without replaying it."""
        journal = self._journal
        if journal is None:
            return
        reader = getattr(journal, "read_entries", None)
        if not callable(reader):
            return
        try:
            read_result = await reader()
            pointer = (
                await asyncio.to_thread(self._checkpoint_store.current)
                if self._checkpoint_store is not None
                else None
            )
        except (CommandJournalError, CheckpointError) as error:
            diagnostic = error.body
            self._journal_failed = True
            self._journal_diagnostic = diagnostic
            return

        grouped: dict[UUID, list[CommandJournalEntry]] = {}
        for entry in read_result.entries:
            grouped.setdefault(entry.command_id, []).append(entry)
        for command_id, events in grouped.items():
            accepted = [entry for entry in events if entry.event is JournalEvent.ACCEPTED]
            running = [entry for entry in events if entry.event is JournalEvent.RUNNING]
            terminal = [entry for entry in events if entry.event is JournalEvent.TERMINAL]
            if len(accepted) != 1 or len(running) > 1 or len(terminal) > 1:
                self._journal_failed = True
                self._journal_diagnostic = ErrorBody(
                    code=ErrorCode.JOURNAL_CORRUPT,
                    message="Command journal lifecycle events are inconsistent",
                    details={"command_id": str(command_id)},
                )
                return
            first = accepted[0]
            if any(
                entry.request_id != first.request_id
                or entry.match_id != first.match_id
                or entry.payload_fingerprint != first.payload_fingerprint
                for entry in events
            ):
                self._journal_failed = True
                self._journal_diagnostic = ErrorBody(
                    code=ErrorCode.JOURNAL_CORRUPT,
                    message="Command journal events disagree about command identity",
                    details={"command_id": str(command_id)},
                )
                return

            if terminal:
                terminal_entry = terminal[0]
                status = terminal_entry.status
                result = CommandResult(
                    command_id=command_id,
                    request_id=first.request_id,
                    match_id=first.match_id,
                    status=status,
                    accepted_revision=first.accepted_revision,
                    resulting_revision=terminal_entry.resulting_revision,
                    error=terminal_entry.error,
                    checkpoint_id=terminal_entry.checkpoint_id,
                )
            else:
                current = pointer.command_result if pointer is not None else None
                if (
                    running
                    and current is not None
                    and current.command_id == command_id
                    and current.request_id == first.request_id
                    and current.match_id == first.match_id
                ):
                    result = current
                    status = result.status
                elif running:
                    status = CommandStatus.RECOVERY_REQUIRED
                    result = CommandResult(
                        command_id=command_id,
                        request_id=first.request_id,
                        match_id=first.match_id,
                        status=status,
                        accepted_revision=first.accepted_revision,
                        resulting_revision=(
                            pointer.revision
                            if pointer is not None and pointer.match_id == first.match_id
                            else first.accepted_revision
                        ),
                        error=ErrorBody(
                            code=ErrorCode.RECOVERY_REQUIRED,
                            message=(
                                "Server restarted during command; it was not replayed and "
                                "requires checkpoint recovery"
                            ),
                        ),
                    )
                    self._journal_failed = True
                    self._journal_diagnostic = result.error
                else:
                    status = CommandStatus.REJECTED
                    result = CommandResult(
                        command_id=command_id,
                        request_id=first.request_id,
                        match_id=first.match_id,
                        status=status,
                        accepted_revision=first.accepted_revision,
                        resulting_revision=(
                            pointer.revision
                            if pointer is not None and pointer.match_id == first.match_id
                            else first.accepted_revision
                        ),
                        error=ErrorBody(
                            code=ErrorCode.SERVER_SHUTTING_DOWN,
                            message="Server stopped before the accepted command began",
                            retryable=True,
                        ),
                    )
                latest = running[0] if running else first
                await journal.append(
                    new_journal_entry(
                        event=JournalEvent.TERMINAL,
                        command_id=command_id,
                        request_id=first.request_id,
                        match_id=first.match_id,
                        recovery_checkpoint_id=latest.recovery_checkpoint_id,
                        checkpoint_id=result.checkpoint_id,
                        operation_name=first.operation_name,
                        payload_fingerprint=first.payload_fingerprint,
                        payload=first.payload,
                        accepted_revision=first.accepted_revision,
                        expected_revision=first.expected_revision,
                        status=status,
                        resulting_revision=result.resulting_revision,
                        error=result.error,
                    )
                )

            if first.request_id in self._requests:
                self._journal_failed = True
                self._journal_diagnostic = ErrorBody(
                    code=ErrorCode.JOURNAL_CORRUPT,
                    message="Request ID appears more than once in the command journal",
                )
                return
            record = _CommandRecord(
                receipt=CommandReceipt(
                    command_id=command_id,
                    request_id=first.request_id,
                    match_id=first.match_id,
                    status=status,
                    accepted_revision=first.accepted_revision,
                ),
                payload_fingerprint=first.payload_fingerprint,
                operation_name=first.operation_name,
                journal_payload=first.payload,
                expected_revision=first.expected_revision,
                recovery_checkpoint_id=(running[0].recovery_checkpoint_id if running else None),
                result=result,
            )
            record.completed.set()
            self._commands[command_id] = record
            self._requests[first.request_id] = record

    def set_recovery_checkpoint_provider(self, provider: RecoveryCheckpointProvider) -> None:
        """Install the trusted checkpoint capture used before emulator mutations."""
        if self._recovery_checkpoint_provider is not None:
            return
        self._recovery_checkpoint_provider = provider

    def set_recovery_rollback_provider(self, provider: RecoveryRollbackProvider) -> None:
        """Install the trusted restore operation for failed emulator mutations."""
        if self._recovery_rollback_provider is not None:
            return
        self._recovery_rollback_provider = provider

    def set_input_release_provider(self, provider: InputReleaseProvider) -> None:
        """Install the trusted bridge operation that releases every held button."""
        if self._input_release_provider is not None:
            return
        self._input_release_provider = provider

    async def stop(self) -> None:
        """Stop accepting work, drain accepted commands, and surface shutdown failures."""
        async with self._accept_lock:
            if self._stopped:
                return
            self._accepting = False
            worker = self._worker
            self._stopped = True
        if worker is None:
            return

        try:
            async with asyncio.timeout(self._shutdown_timeout):
                await self._queue.join()
        except TimeoutError:
            self._forced_shutdown = True
            if self._running is not None:
                await self._require_recovery(self._running, "Controller shutdown deadline expired")
            await self._reject_pending_shutdown()
            worker.cancel()
            done, _ = await asyncio.wait({worker}, timeout=self._shutdown_cancel_timeout)
            if worker not in done:
                raise MatchControllerError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Executor did not stop within the shutdown cancellation deadline",
                )
            try:
                worker.result()
            except asyncio.CancelledError:
                pass
        else:
            await self._queue.put(None)
            await worker
        self._worker = None

    async def create_match(self) -> MatchSummary:
        """Create the one fixed Versus match in setup state."""
        async with self._state_lock:
            if any(
                record.summary.lifecycle is not MatchLifecycle.CLOSED
                for record in self._matches.values()
            ):
                raise MatchControllerError(
                    ErrorCode.ACTIVE_MATCH_EXISTS, "A match is already active"
                )
            match_id = uuid4()
            summary = MatchSummary(
                match_id=match_id,
                revision=0,
                lifecycle=MatchLifecycle.SETUP,
                configuration=FixedMatchConfiguration(),
                slots=(
                    PlayerSlotState(slot=PlayerSlot.SLOT_1, status=SlotStatus.OPEN),
                    PlayerSlotState(slot=PlayerSlot.SLOT_2, status=SlotStatus.OPEN),
                ),
                created_at=datetime.now(UTC),
            )
            self._matches[match_id] = _MatchRecord(summary)
            return summary

    async def adopt_recovered_match(
        self,
        summary: MatchSummary,
        observation: MatchObservation,
        credential_hashes: Mapping[PlayerSlot, str],
    ) -> None:
        """Restore the active match owner from a validated durable checkpoint."""
        if (
            summary.lifecycle is not MatchLifecycle.PLAYABLE
            or observation.match_id != summary.match_id
            or observation.revision != summary.revision
            or len(credential_hashes) != 2
        ):
            raise ValueError("Recovered match metadata is incomplete or inconsistent")
        credentials = {slot: bytes.fromhex(digest) for slot, digest in credential_hashes.items()}
        if any(len(digest) != 32 for digest in credentials.values()):
            raise ValueError("Recovered credential hashes must be SHA-256 digests")
        async with self._state_lock:
            if self._matches:
                raise MatchControllerError(
                    ErrorCode.ACTIVE_MATCH_EXISTS,
                    "Cannot adopt a recovered match when controller state already exists",
                )
            self._matches[summary.match_id] = _MatchRecord(
                summary=summary, credentials=credentials, observation=observation
            )

    async def credential_hashes(self, match_id: UUID) -> dict[PlayerSlot, str]:
        """Return private one-way verifiers for persistence beside trusted checkpoints."""
        async with self._state_lock:
            match = self._require_match(match_id)
            return {slot: digest.hex() for slot, digest in match.credentials.items()}

    async def join_slot(
        self,
        match_id: UUID,
        slot: PlayerSlot,
        *,
        display_name: str | None = None,
    ) -> JoinSlotResponse:
        """Claim one open slot and return its high-entropy credential once."""
        async with self._state_lock:
            record = self._require_match(match_id)
            if record.summary.lifecycle is MatchLifecycle.CLOSED:
                raise MatchControllerError(ErrorCode.MATCH_CLOSED, "The match is closed")
            if record.summary.lifecycle is not MatchLifecycle.SETUP:
                raise MatchControllerError(
                    ErrorCode.SLOT_UNAVAILABLE, "Player slots are locked after setup"
                )
            if slot in record.credentials:
                raise MatchControllerError(ErrorCode.SLOT_UNAVAILABLE, "The player slot is taken")
            token = secrets.token_urlsafe(32)
            record.credentials[slot] = hashlib.sha256(token.encode("utf-8")).digest()
            slots = tuple(
                PlayerSlotState(
                    slot=current.slot,
                    status=SlotStatus.JOINED if current.slot is slot else current.status,
                    display_name=display_name if current.slot is slot else current.display_name,
                )
                for current in record.summary.slots
            )
            record.summary = record.summary.model_copy(update={"slots": slots})
            return JoinSlotResponse(match=record.summary, player_slot=slot, credential=token)

    async def activate_match(
        self,
        match_id: UUID,
        observation: MatchObservation,
        *,
        request_id: UUID,
    ) -> CommandReceipt:
        """Publish the first verified playable boundary after setup navigation."""

        async def activate() -> MutationOutcome:
            async with self._state_lock:
                record = self._require_match(match_id)
                if record.summary.lifecycle is not MatchLifecycle.SETUP:
                    raise CommandRejected(
                        ErrorCode.INVALID_REQUEST, "Only a setup match can be activated"
                    )
                if len(record.credentials) != 2:
                    raise CommandRejected(
                        ErrorCode.SLOT_UNAVAILABLE, "Both player slots must join before activation"
                    )
                self._validate_observation(record, observation, require_advance=False)
                if observation.action_readiness is not ActionReadiness.READY:
                    raise CommandRejected(
                        ErrorCode.OBSERVATION_UNAVAILABLE,
                        "Initial observation is not at a recognized playable input boundary",
                    )
                if observation.revision <= record.summary.revision:
                    raise CommandRejected(
                        ErrorCode.STALE_REVISION,
                        "Initial observation must advance beyond the setup revision",
                    )
                return MutationOutcome(observation=observation, lifecycle=MatchLifecycle.PLAYABLE)

        return await self.submit_serialized_mutation(
            match_id=match_id,
            request_id=request_id,
            operation_name="activate_match",
            payload={"match_id": str(match_id), "observation_revision": observation.revision},
            expected_revision=0,
            handler=activate,
            mutates_emulator=False,
        )

    async def inspect_match(self, match_id: UUID) -> MatchSummary:
        async with self._state_lock:
            return self._require_match(match_id).summary

    async def require_joined_credential(self, match_id: UUID, credential: SecretStr) -> None:
        """Authorize a named server operation without exposing stored credentials."""
        async with self._state_lock:
            if not self._has_any_credential(self._require_match(match_id), credential):
                raise MatchControllerError(
                    ErrorCode.INVALID_CREDENTIAL, "A joined player credential is required"
                )

    async def current_state(self, match_id: UUID) -> MatchStateSnapshot:
        """Read lifecycle and the last committed observation under one lock."""
        async with self._state_lock:
            record = self._require_match(match_id)
            return MatchStateSnapshot(record.summary, record.observation)

    async def current_observation(self, match_id: UUID) -> MatchObservation:
        """Read a settled observation, rejecting reads while a mutation is active."""
        async with self._state_lock:
            record = self._require_match(match_id)
            if record.summary.lifecycle is MatchLifecycle.EXECUTING:
                raise MatchControllerError(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "A command is executing; read the match state for the last committed boundary",
                    retryable=True,
                    details={"current_revision": record.summary.revision},
                )
            if record.observation is None:
                raise MatchControllerError(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "No committed match observation is available",
                )
            return record.observation

    async def close_match(
        self,
        match_id: UUID,
        credential: SecretStr,
        *,
        request_id: UUID,
    ) -> CommandReceipt:
        """Queue an authenticated close after all earlier accepted work."""

        async def close() -> MutationOutcome:
            async with self._state_lock:
                record = self._require_match(match_id)
                if not self._has_any_credential(record, credential):
                    raise CommandRejected(
                        ErrorCode.INVALID_CREDENTIAL, "A joined player credential is required"
                    )
                if record.summary.lifecycle is MatchLifecycle.CLOSED:
                    return MutationOutcome(lifecycle=MatchLifecycle.CLOSED)
                return MutationOutcome(lifecycle=MatchLifecycle.CLOSED)

        return await self.submit_serialized_mutation(
            match_id=match_id,
            request_id=request_id,
            operation_name="close_match",
            payload={"match_id": str(match_id), "operation": "close_match"},
            expected_revision=None,
            handler=close,
            mutates_emulator=False,
            allow_recovery=True,
        )

    async def submit_command(self, request: CommandRequest) -> CommandReceipt:
        """Accept an idempotent gameplay request for ordered execution."""
        payload = request.model_dump(mode="json", exclude={"credential"})
        fingerprint = _fingerprint({"kind": "gameplay", "payload": payload})
        async with self._accept_lock:
            existing = self._requests.get(request.request_id)
            if existing is not None:
                if existing.payload_fingerprint != fingerprint:
                    raise MatchControllerError(
                        ErrorCode.REQUEST_ID_CONFLICT,
                        "Request ID was already used with a different payload",
                    )
                return self._receipt(existing)
            self._require_accepting()
            async with self._state_lock:
                self._require_match(request.match_id)
            self._check_capacity()
            record = self._new_record(
                match_id=request.match_id,
                request_id=request.request_id,
                accepted_revision=request.expected_revision,
                fingerprint=fingerprint,
                request=request,
                operation_name="gameplay",
                journal_payload=payload,
                expected_revision=request.expected_revision,
                mutates_emulator=True,
            )
            await self._journal_and_enqueue(record)
            return record.receipt

    async def submit_serialized_mutation(
        self,
        *,
        match_id: UUID,
        request_id: UUID,
        operation_name: str,
        payload: BaseModel | Mapping[str, Any],
        expected_revision: int | None,
        handler: MutationHandler,
        mutates_emulator: bool = True,
        allow_recovery: bool = False,
    ) -> CommandReceipt:
        """Queue trusted server work on the same lane as gameplay commands.

        Debug operations, frame/input control, checkpoint restore, and setup
        navigation must use this method. It is not a client-facing arbitrary
        callback interface; HTTP handlers should provide fixed named operations.
        """
        if mutates_emulator and expected_revision is None:
            raise ValueError("Emulator mutations require an expected revision")
        payload_dict = (
            payload.model_dump(mode="json") if isinstance(payload, BaseModel) else dict(payload)
        )
        fingerprint = _fingerprint(
            {
                "kind": operation_name,
                "match_id": str(match_id),
                "expected_revision": expected_revision,
                "mutates_emulator": mutates_emulator,
                "allow_recovery": allow_recovery,
                "payload": payload_dict,
            }
        )
        async with self._accept_lock:
            existing = self._requests.get(request_id)
            if existing is not None:
                if existing.payload_fingerprint != fingerprint:
                    raise MatchControllerError(
                        ErrorCode.REQUEST_ID_CONFLICT,
                        "Request ID was already used with a different payload",
                    )
                return self._receipt(existing)
            self._require_accepting()
            self._check_capacity()
            async with self._state_lock:
                current_revision = self._require_match(match_id).summary.revision
            accepted_revision = current_revision if expected_revision is None else expected_revision
            record = self._new_record(
                match_id=match_id,
                request_id=request_id,
                accepted_revision=accepted_revision,
                fingerprint=fingerprint,
                handler=handler,
                operation_name=operation_name,
                journal_payload=_without_credentials(payload_dict),
                expected_revision=expected_revision,
                mutates_emulator=mutates_emulator,
                allow_recovery=allow_recovery,
            )
            await self._journal_and_enqueue(record)
            return record.receipt

    async def command_status(self, match_id: UUID, command_id: UUID) -> CommandResult:
        record = self._commands.get(command_id)
        if record is None or record.receipt.match_id != match_id:
            raise MatchControllerError(ErrorCode.COMMAND_NOT_FOUND, "Command was not found")
        if record.result is not None:
            return record.result
        return CommandResult(
            command_id=record.receipt.command_id,
            request_id=record.receipt.request_id,
            match_id=record.receipt.match_id,
            status=record.receipt.status,
            accepted_revision=record.receipt.accepted_revision,
        )

    async def wait_for_command(
        self,
        match_id: UUID,
        command_id: UUID,
        *,
        timeout: float,
    ) -> CommandResult:
        """Wait for a terminal result; timeout never cancels accepted work."""
        if timeout <= 0:
            raise ValueError("Command wait timeout must be positive")
        record = self._commands.get(command_id)
        if record is None or record.receipt.match_id != match_id:
            raise MatchControllerError(ErrorCode.COMMAND_NOT_FOUND, "Command was not found")
        if record.result is None:
            try:
                async with asyncio.timeout(timeout):
                    await record.completed.wait()
            except TimeoutError as error:
                raise MatchControllerError(
                    ErrorCode.TIMEOUT,
                    "Client wait timed out; the command continues on the server",
                    retryable=True,
                ) from error
        return await self.command_status(match_id, command_id)

    async def _run_queue(self) -> None:
        while not self._forced_shutdown:
            record = await self._queue.get()
            try:
                if record is None:
                    return
                self._running = record
                record.receipt = record.receipt.model_copy(update={"status": CommandStatus.RUNNING})
                try:
                    if self._journal_failed:
                        await self._finish(
                            record,
                            CommandStatus.RECOVERY_REQUIRED,
                            error=ErrorBody(
                                code=ErrorCode.RECOVERY_REQUIRED,
                                message="Command journal failed; queued work was not executed",
                            ),
                        )
                        continue
                    if (
                        record.mutates_emulator
                        and not record.allow_recovery
                        and self._recovery_checkpoint_provider is not None
                    ):
                        record.recovery_checkpoint_id = await self._recovery_checkpoint_provider(
                            record.receipt.match_id,
                            record.receipt.command_id,
                            record.expected_revision,
                        )
                    await self._append_journal(record, JournalEvent.RUNNING, CommandStatus.RUNNING)
                    if record.request is not None:
                        await self._execute_gameplay(record)
                    else:
                        await self._execute_mutation(record)
                except CommandJournalError as error:
                    self._journal_failed = True
                    self._accepting = False
                    self._journal_diagnostic = error.body
                    await self._require_recovery(
                        record,
                        f"Command journal write failed ({type(error).__name__})",
                        diagnostic=error.body,
                    )
                except CommandRejected as error:
                    release_error = await self._release_held_inputs()
                    if release_error is not None:
                        await self._require_recovery(
                            record,
                            "Command failed and held inputs could not be released",
                            diagnostic=release_error,
                        )
                        continue
                    await self._restore_lifecycle_after_rejection(record)
                    await self._finish(record, CommandStatus.REJECTED, error=error.body)
                except CheckpointError as error:
                    if record.previous_lifecycle is None:
                        release_error = await self._release_held_inputs()
                        if release_error is not None:
                            await self._require_recovery(
                                record,
                                "Command failed and held inputs could not be released",
                                diagnostic=release_error,
                            )
                        else:
                            await self._finish(record, CommandStatus.REJECTED, error=error.body)
                    else:
                        await self._rollback_or_require_recovery(record, error.body)
                except MatchControllerError as error:
                    if record.previous_lifecycle is not None:
                        await self._rollback_or_require_recovery(record, error.body)
                    else:
                        release_error = await self._release_held_inputs()
                        if release_error is not None:
                            await self._require_recovery(
                                record,
                                "Command failed and held inputs could not be released",
                                diagnostic=release_error,
                            )
                        else:
                            await self._finish(record, CommandStatus.REJECTED, error=error.body)
                except asyncio.CancelledError:
                    await self._require_recovery(record, "Controller stopped during execution")
                    raise
                except Exception as error:  # noqa: BLE001 -- unknown executor failures require recovery
                    await self._rollback_or_require_recovery(
                        record,
                        ErrorBody(
                            code=ErrorCode.RECOVERY_REQUIRED,
                            message=(
                                "Mutation failed after execution began; restoring its recovery "
                                f"checkpoint ({type(error).__name__})"
                            ),
                            details={"cause": type(error).__name__},
                        ),
                    )
                finally:
                    self._running = None
            finally:
                self._queue.task_done()

    async def _execute_gameplay(self, record: _CommandRecord) -> None:
        request = record.request
        assert request is not None
        async with self._state_lock:
            match = self._require_match(request.match_id)
            summary = match.summary
            if summary.lifecycle is MatchLifecycle.CLOSED:
                raise MatchControllerError(ErrorCode.MATCH_CLOSED, "The match is closed")
            if summary.lifecycle is MatchLifecycle.FINISHED:
                raise MatchControllerError(ErrorCode.MATCH_FINISHED, "The match is finished")
            if summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED:
                raise MatchControllerError(
                    ErrorCode.RECOVERY_REQUIRED, "Restore a checkpoint before submitting commands"
                )
            if summary.lifecycle is not MatchLifecycle.PLAYABLE:
                raise MatchControllerError(
                    ErrorCode.INVALID_REQUEST, "The match is not at a playable boundary"
                )
            if not self._has_slot_credential(match, request.player_slot, request.credential):
                raise MatchControllerError(
                    ErrorCode.INVALID_CREDENTIAL, "Invalid player credential"
                )
            if request.expected_revision != summary.revision:
                raise MatchControllerError(
                    ErrorCode.STALE_REVISION,
                    "Expected revision does not match the current committed state",
                    details={"current_revision": summary.revision},
                )
            observation = match.observation
            if observation is None:
                raise MatchControllerError(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "No committed observation is available",
                )
            if observation.revision != summary.revision:
                raise MatchControllerError(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "Match revision and observation revision disagree",
                )
            if observation.action_readiness is not ActionReadiness.READY:
                raise MatchControllerError(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "The observed UI boundary is not ready for command execution",
                )
            battle = observation.game_state.battle.value
            if battle is None:
                raise MatchControllerError(
                    ErrorCode.OBSERVATION_UNAVAILABLE, "Live battle data is unavailable"
                )
            expected_slot = 1 if request.player_slot is PlayerSlot.SLOT_1 else 2
            if battle.active_player_slot != expected_slot:
                raise MatchControllerError(ErrorCode.NOT_YOUR_TURN, "It is not this player's turn")
            match.summary = summary.model_copy(update={"lifecycle": MatchLifecycle.EXECUTING})
            record.previous_lifecycle = summary.lifecycle

        if self._executor is None:
            raise CommandRejected(
                ErrorCode.UNSUPPORTED_FEATURE,
                "Gameplay execution is not configured yet",
            )
        outcome = await self._executor.execute(request, observation)
        await self._apply_outcome(match, record, outcome, current_revision=summary.revision)

    async def _execute_mutation(self, record: _CommandRecord) -> None:
        handler = record.handler
        if handler is None:
            raise RuntimeError("Queued mutation has no handler")
        async with self._state_lock:
            match = self._require_match(record.receipt.match_id)
            lifecycle = match.summary.lifecycle
            if lifecycle is MatchLifecycle.CLOSED:
                raise MatchControllerError(ErrorCode.MATCH_CLOSED, "The match is closed")
            if lifecycle is MatchLifecycle.FINISHED and not record.allow_recovery:
                raise MatchControllerError(ErrorCode.MATCH_FINISHED, "The match is finished")
            if lifecycle is MatchLifecycle.RECOVERY_REQUIRED and (
                not record.allow_recovery or record.operation_name != "checkpoint_restore"
            ):
                raise MatchControllerError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Only explicit checkpoint restoration is allowed while recovery is required",
                )
            if (
                record.expected_revision is not None
                and record.expected_revision != match.summary.revision
            ):
                raise MatchControllerError(
                    ErrorCode.STALE_REVISION,
                    "Expected revision does not match the current committed state",
                    details={"current_revision": match.summary.revision},
                )
            current_revision = match.summary.revision
            if record.mutates_emulator:
                match.summary = match.summary.model_copy(
                    update={"lifecycle": MatchLifecycle.EXECUTING}
                )
                record.previous_lifecycle = lifecycle

        outcome = await handler()
        if record.mutates_emulator and outcome.observation is None:
            raise RuntimeError("An emulator mutation must return a committed observation")
        await self._apply_outcome(match, record, outcome, current_revision=current_revision)

    async def _apply_outcome(
        self,
        match: _MatchRecord,
        record: _CommandRecord,
        outcome: MutationOutcome,
        *,
        current_revision: int,
    ) -> None:
        if outcome.status not in {
            CommandStatus.COMPLETED,
            CommandStatus.ROLLED_BACK,
            CommandStatus.RECOVERY_REQUIRED,
        }:
            raise RuntimeError("Executor returned a nonterminal command status")
        if outcome.status is CommandStatus.RECOVERY_REQUIRED:
            release_error = await self._release_held_inputs()
            if release_error is not None:
                outcome = MutationOutcome(
                    observation=outcome.observation,
                    lifecycle=MatchLifecycle.RECOVERY_REQUIRED,
                    status=CommandStatus.RECOVERY_REQUIRED,
                    error=_combine_errors(outcome.error, release_error),
                    checkpoint_id=outcome.checkpoint_id,
                    commit_checkpoint=outcome.commit_checkpoint,
                )
        async with self._state_lock:
            if self._forced_shutdown:
                return
            if outcome.observation is not None:
                if outcome.observation.match_id != match.summary.match_id:
                    raise RuntimeError("Executor returned an observation for another match")
                if outcome.observation.revision <= current_revision:
                    raise RuntimeError("Executor did not advance the match revision")
                current_revision = outcome.observation.revision
            elif record.mutates_emulator:
                raise RuntimeError("Emulator mutation completed without a new observation")
            lifecycle = outcome.lifecycle or MatchLifecycle.PLAYABLE
            if outcome.status is CommandStatus.RECOVERY_REQUIRED:
                lifecycle = MatchLifecycle.RECOVERY_REQUIRED
            if record.operation_name == "activate_match":
                allowed_lifecycles = {MatchLifecycle.PLAYABLE}
            elif record.operation_name == "close_match":
                allowed_lifecycles = {MatchLifecycle.CLOSED}
            else:
                allowed_lifecycles = {
                    MatchLifecycle.PLAYABLE,
                    MatchLifecycle.FINISHED,
                    MatchLifecycle.RECOVERY_REQUIRED,
                }
            if lifecycle not in allowed_lifecycles:
                raise RuntimeError(f"Invalid terminal match lifecycle: {lifecycle.value}")
            if (
                lifecycle is MatchLifecycle.RECOVERY_REQUIRED
                and outcome.status != CommandStatus.RECOVERY_REQUIRED
            ):
                raise RuntimeError("Recovery-required lifecycle needs recovery-required status")
            if (
                outcome.status is CommandStatus.ROLLED_BACK
                and lifecycle is not MatchLifecycle.PLAYABLE
            ):
                raise RuntimeError("A successful rollback must return to a playable boundary")
            next_summary = match.summary.model_copy(
                update={"revision": current_revision, "lifecycle": lifecycle}
            )
            if outcome.commit_checkpoint is not None:
                if outcome.checkpoint_id is None:
                    raise RuntimeError("Checkpoint commit needs a checkpoint ID")
                proposed_result = CommandResult(
                    command_id=record.receipt.command_id,
                    request_id=record.receipt.request_id,
                    match_id=record.receipt.match_id,
                    status=outcome.status,
                    accepted_revision=record.receipt.accepted_revision,
                    resulting_revision=current_revision,
                    error=outcome.error,
                    checkpoint_id=outcome.checkpoint_id,
                )
                await outcome.commit_checkpoint(proposed_result)
                if self._forced_shutdown:
                    return
            # Persist the terminal record before publishing the result or state.
            persisted = await self._finish(
                record,
                outcome.status,
                resulting_revision=current_revision,
                error=outcome.error,
                checkpoint_id=outcome.checkpoint_id,
            )
            if not persisted:
                release_error = await self._release_held_inputs()
                match.summary = match.summary.model_copy(
                    update={"lifecycle": MatchLifecycle.RECOVERY_REQUIRED}
                )
                if release_error is not None and record.result is not None:
                    record.result = record.result.model_copy(
                        update={"error": _combine_errors(record.result.error, release_error)}
                    )
                return
            if outcome.observation is not None:
                match.observation = outcome.observation
            match.summary = next_summary

    async def _require_recovery(
        self,
        record: _CommandRecord,
        message: str,
        *,
        diagnostic: ErrorBody | None = None,
    ) -> None:
        release_error = await self._release_held_inputs()
        details = _diagnostic_details(diagnostic)
        if release_error is not None:
            details.update(_diagnostic_details(release_error))
            details["input_release_failed"] = True
        error = ErrorBody(
            code=ErrorCode.RECOVERY_REQUIRED,
            message=message,
            retryable=False,
            details=details,
        )
        async with self._state_lock:
            match = self._matches.get(record.receipt.match_id)
            if match is not None and match.summary.lifecycle is not MatchLifecycle.CLOSED:
                match.summary = match.summary.model_copy(
                    update={"lifecycle": MatchLifecycle.RECOVERY_REQUIRED}
                )
        await self._finish(record, CommandStatus.RECOVERY_REQUIRED, error=error)

    async def _rollback_or_require_recovery(
        self, record: _CommandRecord, original_error: ErrorBody
    ) -> None:
        release_error = await self._release_held_inputs()
        if release_error is not None:
            await self._require_recovery(
                record,
                "Action failed and held inputs could not be released",
                diagnostic=_combine_errors(original_error, release_error),
            )
            return
        provider = self._recovery_rollback_provider
        checkpoint_id = record.recovery_checkpoint_id
        if provider is None or checkpoint_id is None:
            await self._require_recovery(
                record,
                "Mutation failed and no recovery checkpoint restore is available",
                diagnostic=original_error,
            )
            return
        try:
            outcome = await provider(
                record.receipt.match_id,
                record.receipt.command_id,
                checkpoint_id,
                original_error,
            )
            if outcome.status is not CommandStatus.ROLLED_BACK or outcome.observation is None:
                raise RuntimeError("Recovery restore did not return a rolled-back observation")
            async with self._state_lock:
                match = self._require_match(record.receipt.match_id)
                revision = match.summary.revision
            await self._apply_outcome(match, record, outcome, current_revision=revision)
        except Exception as restore_error:  # noqa: BLE001 -- failed restore requires explicit recovery
            await self._require_recovery(
                record,
                "Action failed and its recovery checkpoint could not be restored",
                diagnostic=ErrorBody(
                    code=ErrorCode.RECOVERY_REQUIRED,
                    message="Checkpoint restoration failed",
                    details={
                        "cause": type(restore_error).__name__,
                        "action_failure_code": original_error.code.value,
                        "action_failure": original_error.message[:200],
                    },
                ),
            )

    async def _release_held_inputs(self) -> ErrorBody | None:
        provider = self._input_release_provider
        if provider is None:
            return None
        try:
            await provider()
        except Exception as error:  # noqa: BLE001 -- unknown key state requires recovery
            return ErrorBody(
                code=ErrorCode.RECOVERY_REQUIRED,
                message="Could not confirm release of held emulator inputs",
                details={"cause": type(error).__name__},
            )
        return None

    async def _restore_lifecycle_after_rejection(self, record: _CommandRecord) -> None:
        if record.previous_lifecycle is None:
            return
        async with self._state_lock:
            match = self._matches.get(record.receipt.match_id)
            if match is not None and match.summary.lifecycle is MatchLifecycle.EXECUTING:
                match.summary = match.summary.model_copy(
                    update={"lifecycle": record.previous_lifecycle}
                )

    async def _finish(
        self,
        record: _CommandRecord,
        status: CommandStatus,
        *,
        resulting_revision: int | None = None,
        error: ErrorBody | None = None,
        checkpoint_id: UUID | None = None,
    ) -> bool:
        if record.result is not None:
            return True
        if resulting_revision is None:
            match = self._matches.get(record.receipt.match_id)
            if match is not None:
                resulting_revision = match.summary.revision
        persisted = True
        try:
            await self._append_journal(
                record,
                JournalEvent.TERMINAL,
                status,
                resulting_revision=resulting_revision,
                error=error,
                checkpoint_id=checkpoint_id,
            )
        except CommandJournalError as journal_error:
            self._journal_failed = True
            self._accepting = False
            self._journal_diagnostic = journal_error.body
            persisted = False
            status = CommandStatus.RECOVERY_REQUIRED
            checkpoint_id = None
            error = ErrorBody(
                code=ErrorCode.RECOVERY_REQUIRED,
                message=(
                    f"Could not persist terminal command result ({type(journal_error).__name__})"
                ),
                details=_diagnostic_details(journal_error.body),
            )
        result = CommandResult(
            command_id=record.receipt.command_id,
            request_id=record.receipt.request_id,
            match_id=record.receipt.match_id,
            status=status,
            accepted_revision=record.receipt.accepted_revision,
            resulting_revision=resulting_revision,
            error=error,
            checkpoint_id=checkpoint_id,
        )
        record.receipt = record.receipt.model_copy(update={"status": status})
        record.result = result
        record.completed.set()
        return persisted

    async def _reject_pending_shutdown(self) -> None:
        while True:
            try:
                record = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                if record is not None:
                    await self._finish(
                        record,
                        CommandStatus.REJECTED,
                        error=ErrorBody(
                            code=ErrorCode.SERVER_SHUTTING_DOWN,
                            message="Command was accepted but not started before shutdown",
                            retryable=True,
                        ),
                    )
            finally:
                self._queue.task_done()

    def _new_record(
        self,
        *,
        match_id: UUID,
        request_id: UUID,
        accepted_revision: int,
        fingerprint: str,
        request: CommandRequest | None = None,
        handler: MutationHandler | None = None,
        operation_name: str | None = None,
        journal_payload: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        mutates_emulator: bool = False,
        allow_recovery: bool = False,
    ) -> _CommandRecord:
        record = _CommandRecord(
            receipt=CommandReceipt(
                command_id=uuid4(),
                request_id=request_id,
                match_id=match_id,
                status=CommandStatus.QUEUED,
                accepted_revision=accepted_revision,
            ),
            payload_fingerprint=fingerprint,
            request=request,
            handler=handler,
            operation_name=operation_name,
            journal_payload=journal_payload or {},
            expected_revision=expected_revision,
            mutates_emulator=mutates_emulator,
            allow_recovery=allow_recovery,
        )
        self._commands[record.receipt.command_id] = record
        self._requests[request_id] = record
        return record

    def _enqueue(self, record: _CommandRecord) -> None:
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull as error:
            self._commands.pop(record.receipt.command_id, None)
            self._requests.pop(record.receipt.request_id, None)
            raise MatchControllerError(
                ErrorCode.COMMAND_CAPACITY,
                "The command queue is full; no command was accepted",
                retryable=True,
            ) from error

    async def _journal_and_enqueue(self, record: _CommandRecord) -> None:
        if self._queue.full():
            self._commands.pop(record.receipt.command_id, None)
            self._requests.pop(record.receipt.request_id, None)
            raise MatchControllerError(
                ErrorCode.COMMAND_CAPACITY,
                "The command queue is full; no command was accepted",
                retryable=True,
            )
        try:
            await self._append_journal(record, JournalEvent.ACCEPTED, CommandStatus.QUEUED)
        except CommandJournalError as error:
            self._commands.pop(record.receipt.command_id, None)
            self._requests.pop(record.receipt.request_id, None)
            self._journal_failed = True
            self._accepting = False
            self._journal_diagnostic = error.body
            raise MatchControllerError(
                ErrorCode.RECOVERY_REQUIRED,
                "The command was not accepted because its journal entry could not be stored",
                retryable=error.body.retryable,
                details=_diagnostic_details(error.body),
            ) from error
        self._enqueue(record)

    async def _append_journal(
        self,
        record: _CommandRecord,
        event: JournalEvent,
        status: CommandStatus,
        *,
        resulting_revision: int | None = None,
        error: ErrorBody | None = None,
        checkpoint_id: UUID | None = None,
    ) -> None:
        if self._journal is None:
            return
        try:
            entry = new_journal_entry(
                event=event,
                command_id=record.receipt.command_id,
                request_id=record.receipt.request_id,
                match_id=record.receipt.match_id,
                recovery_checkpoint_id=record.recovery_checkpoint_id,
                checkpoint_id=checkpoint_id,
                operation_name=record.operation_name or "unknown",
                payload_fingerprint=record.payload_fingerprint,
                payload=record.journal_payload,
                accepted_revision=record.receipt.accepted_revision,
                expected_revision=record.expected_revision,
                status=status,
                resulting_revision=resulting_revision,
                error=error,
            )
            await self._journal.append(entry)
        except CommandJournalError:
            raise
        except Exception as journal_error:
            diagnostic = ErrorBody(
                code=ErrorCode.STORAGE_UNAVAILABLE,
                message="Command journal backend failed",
                retryable=True,
                details={"cause": type(journal_error).__name__},
            )
            raise CommandJournalError(diagnostic) from journal_error

    def _check_capacity(self) -> None:
        if len(self._commands) >= self._command_capacity:
            raise MatchControllerError(
                ErrorCode.COMMAND_CAPACITY,
                "Command history is full; no command was accepted",
                retryable=False,
            )

    def _require_accepting(self) -> None:
        if self._journal_failed:
            raise MatchControllerError(
                ErrorCode.RECOVERY_REQUIRED,
                "The command journal failed; controller recovery is required before accepting work",
                details=_diagnostic_details(self._journal_diagnostic),
            )
        if not self._accepting or self._stopped:
            raise MatchControllerError(
                ErrorCode.SERVER_SHUTTING_DOWN,
                "The command controller is not accepting work",
                retryable=True,
            )

    def _require_match(self, match_id: UUID) -> _MatchRecord:
        record = self._matches.get(match_id)
        if record is None:
            raise MatchControllerError(ErrorCode.MATCH_NOT_FOUND, "Match was not found")
        return record

    def _has_slot_credential(
        self, match: _MatchRecord, slot: PlayerSlot, credential: SecretStr
    ) -> bool:
        expected = match.credentials.get(slot)
        if expected is None:
            return False
        supplied = hashlib.sha256(credential.get_secret_value().encode("utf-8")).digest()
        return hmac.compare_digest(expected, supplied)

    def _has_any_credential(self, match: _MatchRecord, credential: SecretStr) -> bool:
        supplied = hashlib.sha256(credential.get_secret_value().encode("utf-8")).digest()
        return any(hmac.compare_digest(value, supplied) for value in match.credentials.values())

    def _validate_observation(
        self, match: _MatchRecord, observation: MatchObservation, *, require_advance: bool
    ) -> None:
        if observation.match_id != match.summary.match_id:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Observation belongs to another match")
        if require_advance and observation.revision <= match.summary.revision:
            raise CommandRejected(ErrorCode.STALE_REVISION, "Observation revision did not advance")

    @staticmethod
    def _receipt(record: _CommandRecord) -> CommandReceipt:
        return record.receipt


def _fingerprint(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _diagnostic_details(diagnostic: ErrorBody | None) -> dict[str, str | int | bool | None]:
    if diagnostic is None:
        return {}
    details = dict(diagnostic.details)
    details["failure_code"] = diagnostic.code.value
    details["failure_message"] = diagnostic.message[:200]
    return details


def _combine_errors(primary: ErrorBody | None, secondary: ErrorBody) -> ErrorBody:
    details = _diagnostic_details(primary)
    details["secondary_failure_code"] = secondary.code.value
    details["secondary_failure_message"] = secondary.message[:200]
    details.update({f"secondary_{key}": value for key, value in secondary.details.items()})
    return ErrorBody(
        code=ErrorCode.RECOVERY_REQUIRED,
        message="Mutation recovery could not release emulator inputs",
        details=details,
    )


def _without_credentials(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_credentials(item)
            for key, item in value.items()
            if key not in {"credential", "credentials"}
        }
    if isinstance(value, (list, tuple)):
        return [_without_credentials(item) for item in value]
    return value
