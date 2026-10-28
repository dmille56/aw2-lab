"""Authenticated checkpoint operations on the controller's serialized emulator lane."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4, uuid5

from pydantic import SecretStr

from aw2_lab.checkpoint import (
    CapturedCheckpointState,
    CheckpointBridge,
    CheckpointError,
    capture_checkpoint_state,
    checkpoint_observation_metadata,
    restore_checkpoint_state,
    validate_checkpoint_compatibility,
)
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.command_journal import (
    CommandJournalEntry,
    JournalEvent,
    JsonlCommandJournal,
    new_journal_entry,
)
from aw2_lab.match_contract import (
    CheckpointIdentityMetadata,
    CheckpointManifest,
    CheckpointReference,
    CommandReceipt,
    CommandResult,
    CommandStatus,
    ErrorBody,
    ErrorCode,
    MatchLifecycle,
    MatchSummary,
    PlayerSlot,
    SlotStatus,
)
from aw2_lab.match_controller import CommandRejected, MatchController, MutationOutcome
from aw2_lab.match_observation import (
    MATCH_OBSERVATION_SCHEMA_VERSION,
    ActionReadiness,
    MatchObservationMetadata,
    MatchObservationTracker,
    RevisionCause,
)
from aw2_lab.state_model import GAME_STATE_SCHEMA_VERSION, GameState


@dataclass(frozen=True, slots=True)
class CheckpointRuntime:
    rom_sha256: str
    emulator_build: str
    emulator_mode: Literal["headless", "windowed"]


@dataclass(slots=True)
class CheckpointSession:
    """Shared observation owner; executors must use this tracker after restoration."""

    tracker: MatchObservationTracker
    capture_game_state: Callable[[], Awaitable[GameState]]


class MatchCheckpointService:
    """Client operations accept match/checkpoint IDs, credentials, and archive bytes."""

    def __init__(
        self,
        *,
        controller: MatchController,
        store: CheckpointStore,
        bridge: CheckpointBridge,
        session: CheckpointSession,
        runtime: CheckpointRuntime,
        journal: JsonlCommandJournal | None = None,
    ) -> None:
        self.controller = controller
        self.store = store
        self.bridge = bridge
        self.session = session
        self.runtime = runtime
        self.journal = journal
        self.controller.set_recovery_checkpoint_provider(self.capture_recovery_checkpoint)
        self.controller.set_recovery_rollback_provider(self.restore_recovery_checkpoint)
        self.controller.set_input_release_provider(self.release_inputs)

    async def release_inputs(self) -> None:
        """Release all GBA buttons and require the bridge to confirm a neutral mask."""
        keys = await self.bridge.set_keys(0)
        if keys != 0:
            raise CheckpointError(
                ErrorCode.RECOVERY_REQUIRED,
                "The emulator did not confirm release of held inputs",
                details={"reported_keys": keys},
            )

    async def restore_startup_checkpoint(
        self,
        checkpoint_id: UUID,
        *,
        durable_revision_floor: int,
        interrupted_command: CommandJournalEntry | None = None,
    ) -> CommandResult | None:
        """Restore a committed boundary before accepting work; never replay commands."""
        manifest, state = await asyncio.to_thread(self.store.load, checkpoint_id)
        self._compatible(manifest)
        if manifest.match.lifecycle is not MatchLifecycle.PLAYABLE:
            raise CheckpointError(
                ErrorCode.CHECKPOINT_INCOMPATIBLE,
                "Startup recovery requires a playable checkpoint",
            )
        if set(manifest.slot_credential_hashes) != {PlayerSlot.SLOT_1, PlayerSlot.SLOT_2}:
            raise CheckpointError(
                ErrorCode.CHECKPOINT_INCOMPATIBLE,
                "Checkpoint lacks player credential verifiers required for restart adoption",
            )
        if any(slot.status is not SlotStatus.JOINED for slot in manifest.match.slots):
            raise CheckpointError(
                ErrorCode.CHECKPOINT_INCOMPATIBLE,
                "Startup checkpoint does not have both player slots joined",
            )
        if self.session.tracker.match_id != manifest.match.match_id:
            raise CheckpointError(
                ErrorCode.CHECKPOINT_INCOMPATIBLE,
                "Startup observer does not match the checkpoint",
            )
        tracker = MatchObservationTracker.from_checkpoint(
            checkpoint_observation_metadata(manifest),
            durable_revision_floor=durable_revision_floor,
        )
        await self.release_inputs()
        await restore_checkpoint_state(
            self.bridge,
            manifest,
            state,
            rom_sha256=self.runtime.rom_sha256,
            emulator_build=self.runtime.emulator_build,
            emulator_mode=self.runtime.emulator_mode,
        )
        decoded = await self.session.capture_game_state()
        _validate_restored_units(manifest, decoded)
        observation = tracker.commit_boundary(decoded, cause=RevisionCause.RESTORE)
        if observation.action_readiness is not ActionReadiness.READY:
            raise CheckpointError(
                ErrorCode.RECOVERY_REQUIRED,
                "Startup checkpoint did not restore to a playable input boundary",
            )
        captured = await capture_checkpoint_state(self.bridge)
        if captured.frame != decoded.frame:
            raise CheckpointError(
                ErrorCode.RECOVERY_REQUIRED,
                "Emulator advanced during startup checkpoint restoration",
            )
        summary = manifest.match.model_copy(
            update={"revision": observation.revision, "lifecycle": MatchLifecycle.PLAYABLE}
        )
        new_checkpoint_id = uuid4()
        result = None
        if interrupted_command is not None:
            if self.journal is None or interrupted_command.event is not JournalEvent.RUNNING:
                raise CheckpointError(
                    ErrorCode.JOURNAL_CORRUPT,
                    "Interrupted command cannot be reconciled without its durable journal",
                )
            result = CommandResult(
                command_id=interrupted_command.command_id,
                request_id=interrupted_command.request_id,
                match_id=interrupted_command.match_id,
                status=CommandStatus.ROLLED_BACK,
                accepted_revision=interrupted_command.accepted_revision,
                resulting_revision=observation.revision,
                error=ErrorBody(
                    code=ErrorCode.RECOVERY_REQUIRED,
                    message=(
                        "Server restarted during execution; the pre-action checkpoint was "
                        "restored and the command was not replayed"
                    ),
                ),
                checkpoint_id=new_checkpoint_id,
            )
        fresh_manifest = CheckpointManifest(
            checkpoint_id=new_checkpoint_id,
            match=summary,
            originating_command_id=result.command_id if result is not None else None,
            slot_credential_hashes=manifest.slot_credential_hashes,
            rom_sha256=self.runtime.rom_sha256,
            emulator_build=self.runtime.emulator_build,
            emulator_mode=self.runtime.emulator_mode,
            state_artifact=captured.artifact,
            decoder_schema_version=GAME_STATE_SCHEMA_VERSION,
            observation_schema_version=MATCH_OBSERVATION_SCHEMA_VERSION,
            identity_metadata=CheckpointIdentityMetadata.model_validate(
                tracker.checkpoint_metadata().identity_metadata.to_dict()
            ),
            last_frame=captured.frame,
            created_at=datetime.now(UTC),
        )
        await asyncio.to_thread(self.store.save, fresh_manifest, captured.data)
        await asyncio.to_thread(self.store.commit, new_checkpoint_id, command_result=result)
        if interrupted_command is not None:
            assert result is not None and self.journal is not None
            await self.journal.append(
                new_journal_entry(
                    event=JournalEvent.TERMINAL,
                    command_id=interrupted_command.command_id,
                    request_id=interrupted_command.request_id,
                    match_id=interrupted_command.match_id,
                    recovery_checkpoint_id=interrupted_command.recovery_checkpoint_id,
                    checkpoint_id=new_checkpoint_id,
                    operation_name=interrupted_command.operation_name,
                    payload_fingerprint=interrupted_command.payload_fingerprint,
                    payload=interrupted_command.payload,
                    accepted_revision=interrupted_command.accepted_revision,
                    expected_revision=interrupted_command.expected_revision,
                    status=result.status,
                    resulting_revision=result.resulting_revision,
                    error=result.error,
                )
            )
        self.session.tracker = tracker
        await self.controller.adopt_recovered_match(
            summary, observation, manifest.slot_credential_hashes
        )
        return result

    async def capture_recovery_checkpoint(
        self, match_id: UUID, command_id: UUID, expected_revision: int | None
    ) -> UUID:
        """Durably capture the current playable boundary before a queued mutation runs."""
        snapshot = await self.controller.current_state(match_id)
        observation = snapshot.observation
        if (
            snapshot.summary.lifecycle is not MatchLifecycle.PLAYABLE
            or observation is None
            or observation.action_readiness is not ActionReadiness.READY
        ):
            raise CheckpointError(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "A recovery checkpoint needs a settled playable boundary",
            )
        if expected_revision is not None and snapshot.summary.revision != expected_revision:
            raise CheckpointError(
                ErrorCode.STALE_REVISION,
                "The match changed before its recovery checkpoint was captured",
            )
        if self.session.tracker.read() != observation:
            raise CheckpointError(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Checkpoint observer does not match the controller boundary",
            )
        captured = await capture_checkpoint_state(self.bridge)
        metadata = self.session.tracker.checkpoint_metadata()
        if captured.frame != metadata.last_frame:
            raise CheckpointError(
                ErrorCode.RECOVERY_REQUIRED,
                "Emulator moved beyond the committed boundary before action execution",
            )
        checkpoint_id = uuid5(match_id, f"recovery-before:{command_id}")
        credential_hashes = await self.controller.credential_hashes(match_id)
        manifest = CheckpointManifest(
            checkpoint_id=checkpoint_id,
            match=snapshot.summary,
            originating_command_id=command_id,
            slot_credential_hashes=credential_hashes,
            rom_sha256=self.runtime.rom_sha256,
            emulator_build=self.runtime.emulator_build,
            emulator_mode=self.runtime.emulator_mode,
            state_artifact=captured.artifact,
            decoder_schema_version=GAME_STATE_SCHEMA_VERSION,
            observation_schema_version=MATCH_OBSERVATION_SCHEMA_VERSION,
            identity_metadata=CheckpointIdentityMetadata.model_validate(
                metadata.identity_metadata.to_dict()
            ),
            last_frame=captured.frame,
            created_at=datetime.now(UTC),
        )
        await asyncio.to_thread(self.store.save, manifest, captured.data)
        return checkpoint_id

    async def restore_recovery_checkpoint(
        self,
        match_id: UUID,
        command_id: UUID,
        checkpoint_id: UUID,
        original_error: ErrorBody,
    ) -> MutationOutcome:
        """Restore the pre-action state and rebuild Python observation metadata."""
        current = await self.controller.current_state(match_id)
        self.session.tracker.mark_uncertain("Action failed; recovery restore is in progress")
        manifest, state = await asyncio.to_thread(self.store.load, checkpoint_id)
        self._compatible(manifest)
        self._same_match(manifest, current.summary)
        if manifest.match.lifecycle is not MatchLifecycle.PLAYABLE:
            raise CheckpointError(
                ErrorCode.CHECKPOINT_INCOMPATIBLE,
                "Recovery checkpoint is not at a playable boundary",
            )
        pointer = await asyncio.to_thread(self.store.current)
        floor = max(current.summary.revision, self.session.tracker.revision)
        if pointer is not None and pointer.match_id == match_id:
            floor = max(floor, pointer.revision)
        restored_tracker = MatchObservationTracker.from_checkpoint(
            checkpoint_observation_metadata(manifest), durable_revision_floor=floor
        )
        try:
            await self.release_inputs()
            await restore_checkpoint_state(
                self.bridge,
                manifest,
                state,
                rom_sha256=self.runtime.rom_sha256,
                emulator_build=self.runtime.emulator_build,
                emulator_mode=self.runtime.emulator_mode,
            )
            decoded = await self.session.capture_game_state()
            _validate_restored_units(manifest, decoded)
            observation = restored_tracker.commit_boundary(decoded, cause=RevisionCause.ROLLBACK)
            if observation.action_readiness is not ActionReadiness.READY:
                raise CheckpointError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Restored recovery checkpoint is not ready for commands",
                )
            captured = await capture_checkpoint_state(self.bridge)
            if captured.frame != decoded.frame:
                raise CheckpointError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Emulator advanced during recovery checkpoint restoration",
                )
        except BaseException:
            self.session.tracker.mark_uncertain("Action rollback did not complete")
            raise

        self.session.tracker = restored_tracker
        summary = current.summary.model_copy(
            update={"revision": observation.revision, "lifecycle": MatchLifecycle.PLAYABLE}
        )
        credential_hashes = await self.controller.credential_hashes(match_id)
        checkpoint = self._outcome(
            uuid5(match_id, f"rollback:{command_id}"),
            summary,
            captured,
            restored_tracker.checkpoint_metadata(),
            credential_hashes,
        )
        return MutationOutcome(
            observation=observation,
            lifecycle=MatchLifecycle.PLAYABLE,
            status=CommandStatus.ROLLED_BACK,
            error=original_error,
            checkpoint_id=checkpoint.checkpoint_id,
            commit_checkpoint=checkpoint.commit_checkpoint,
        )

    async def create(
        self,
        match_id: UUID,
        credential: SecretStr,
        *,
        request_id: UUID,
        expected_revision: int,
    ) -> CommandReceipt:
        await self.controller.require_joined_credential(match_id, credential)
        checkpoint_id = uuid5(match_id, f"create:{request_id}")

        async def capture() -> MutationOutcome:
            await self.controller.require_joined_credential(match_id, credential)
            snapshot = await self.controller.current_state(match_id)
            observation = snapshot.observation
            if (
                snapshot.summary.lifecycle is not MatchLifecycle.PLAYABLE
                or observation is None
                or observation.action_readiness is not ActionReadiness.READY
            ):
                raise CommandRejected(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "Checkpoint creation needs a playable boundary",
                )
            if self.session.tracker.read() != observation:
                raise CommandRejected(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "Checkpoint observer does not match the controller boundary",
                )
            captured = await capture_checkpoint_state(self.bridge)
            metadata = self.session.tracker.checkpoint_metadata()
            if captured.frame != metadata.last_frame:
                raise CheckpointError(
                    ErrorCode.RECOVERY_REQUIRED, "Emulator moved beyond the committed boundary"
                )
            credential_hashes = await self.controller.credential_hashes(match_id)
            return self._outcome(
                checkpoint_id, snapshot.summary, captured, metadata, credential_hashes
            )

        return await self.controller.submit_serialized_mutation(
            match_id=match_id,
            request_id=request_id,
            operation_name="checkpoint_create",
            payload={"match_id": str(match_id)},
            expected_revision=expected_revision,
            handler=capture,
            mutates_emulator=False,
        )

    async def export(self, match_id: UUID, checkpoint_id: UUID, credential: SecretStr) -> bytes:
        await self.controller.require_joined_credential(match_id, credential)
        manifest, _ = await asyncio.to_thread(self.store.load, checkpoint_id)
        self._same_match(manifest, await self.controller.inspect_match(match_id))
        return await asyncio.to_thread(self.store.export_archive, checkpoint_id)

    async def import_archive(
        self, match_id: UUID, data: bytes, credential: SecretStr
    ) -> CheckpointReference:
        await self.controller.require_joined_credential(match_id, credential)
        manifest, state = CheckpointStore.decode_archive(data)
        self._compatible(manifest)
        self._same_match(manifest, await self.controller.inspect_match(match_id))
        return await asyncio.to_thread(self.store.save, manifest, state)

    async def restore(
        self,
        match_id: UUID,
        checkpoint_id: UUID,
        credential: SecretStr,
        *,
        request_id: UUID,
        expected_revision: int,
    ) -> CommandReceipt:
        await self.controller.require_joined_credential(match_id, credential)
        new_checkpoint_id = uuid5(match_id, f"restore:{request_id}")

        async def restore() -> MutationOutcome:
            await self.controller.require_joined_credential(match_id, credential)
            current = await self.controller.current_state(match_id)
            try:
                if current.observation is None:
                    raise CheckpointError(
                        ErrorCode.OBSERVATION_UNAVAILABLE,
                        "Restore requires an initialized match with joined player slots",
                    )
                if self.session.tracker.match_id != match_id:
                    raise CheckpointError(
                        ErrorCode.INVALID_REQUEST, "Checkpoint observer belongs to another match"
                    )
                manifest, state = await asyncio.to_thread(self.store.load, checkpoint_id)
                self._compatible(manifest)
                self._same_match(manifest, current.summary)
                if manifest.match.lifecycle is not MatchLifecycle.PLAYABLE:
                    raise CheckpointError(
                        ErrorCode.CHECKPOINT_INCOMPATIBLE,
                        "Only playable-turn checkpoints can be restored by this observer",
                    )
                pointer = await asyncio.to_thread(self.store.current)
                floor = max(
                    current.summary.revision, manifest.match.revision, self.session.tracker.revision
                )
                if pointer is not None and pointer.match_id == match_id:
                    floor = max(floor, pointer.revision)
                metadata = checkpoint_observation_metadata(manifest)
                restored_tracker = MatchObservationTracker.from_checkpoint(
                    metadata, durable_revision_floor=floor
                )
            except CheckpointError as error:
                raise CommandRejected(
                    error.body.code,
                    str(error),
                    retryable=error.body.retryable,
                    details=error.body.details,
                ) from error
            except ValueError as error:
                raise CommandRejected(
                    ErrorCode.CHECKPOINT_INCOMPATIBLE,
                    "Checkpoint revision or identity metadata cannot be restored",
                ) from error

            # From here onward any failure must keep the match recovery-required.
            try:
                await self.release_inputs()
                await restore_checkpoint_state(
                    self.bridge,
                    manifest,
                    state,
                    rom_sha256=self.runtime.rom_sha256,
                    emulator_build=self.runtime.emulator_build,
                    emulator_mode=self.runtime.emulator_mode,
                )
                decoded = await self.session.capture_game_state()
                _validate_restored_units(manifest, decoded)
                observation = restored_tracker.commit_boundary(decoded, cause=RevisionCause.RESTORE)
                if observation.action_readiness is not ActionReadiness.READY:
                    raise CheckpointError(
                        ErrorCode.RECOVERY_REQUIRED, "Restored checkpoint is not ready for commands"
                    )
                captured = await capture_checkpoint_state(self.bridge)
                if captured.frame != decoded.frame:
                    raise CheckpointError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "Emulator advanced during checkpoint restoration",
                    )
            except BaseException:
                self.session.tracker.mark_uncertain("Checkpoint restoration did not complete")
                raise
            self.session.tracker = restored_tracker
            summary = current.summary.model_copy(
                update={
                    "revision": observation.revision,
                    "lifecycle": MatchLifecycle.PLAYABLE,
                }
            )
            outcome = self._outcome(
                new_checkpoint_id,
                summary,
                captured,
                restored_tracker.checkpoint_metadata(),
                await self.controller.credential_hashes(match_id),
            )
            return MutationOutcome(
                observation=observation,
                lifecycle=MatchLifecycle.PLAYABLE,
                checkpoint_id=outcome.checkpoint_id,
                commit_checkpoint=outcome.commit_checkpoint,
            )

        return await self.controller.submit_serialized_mutation(
            match_id=match_id,
            request_id=request_id,
            operation_name="checkpoint_restore",
            payload={"checkpoint_id": str(checkpoint_id)},
            expected_revision=expected_revision,
            handler=restore,
            allow_recovery=True,
        )

    def _compatible(self, manifest: CheckpointManifest) -> None:
        validate_checkpoint_compatibility(
            manifest,
            rom_sha256=self.runtime.rom_sha256,
            emulator_build=self.runtime.emulator_build,
            emulator_mode=self.runtime.emulator_mode,
        )

    @staticmethod
    def _same_match(manifest: CheckpointManifest, summary: MatchSummary) -> None:
        if (
            manifest.match.match_id != summary.match_id
            or manifest.match.configuration != summary.configuration
        ):
            raise CheckpointError(
                ErrorCode.CHECKPOINT_INCOMPATIBLE,
                "Checkpoint belongs to a different match or configuration",
            )

    def _outcome(
        self,
        checkpoint_id: UUID,
        summary: MatchSummary,
        captured: CapturedCheckpointState,
        metadata: MatchObservationMetadata,
        credential_hashes: dict[PlayerSlot, str],
    ) -> MutationOutcome:
        async def commit(result: CommandResult) -> None:
            manifest = CheckpointManifest(
                checkpoint_id=checkpoint_id,
                match=summary,
                originating_command_id=result.command_id,
                slot_credential_hashes=credential_hashes,
                rom_sha256=self.runtime.rom_sha256,
                emulator_build=self.runtime.emulator_build,
                emulator_mode=self.runtime.emulator_mode,
                state_artifact=captured.artifact,
                decoder_schema_version=GAME_STATE_SCHEMA_VERSION,
                observation_schema_version=MATCH_OBSERVATION_SCHEMA_VERSION,
                identity_metadata=CheckpointIdentityMetadata.model_validate(
                    metadata.identity_metadata.to_dict()
                ),
                last_frame=captured.frame,
                created_at=datetime.now(UTC),
            )

            def persist() -> None:
                self.store.save(manifest, captured.data)
                self.store.commit(checkpoint_id, command_result=result)

            # An in-progress filesystem commit must settle before cancellation is observed.
            task = asyncio.create_task(asyncio.to_thread(persist))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

        return MutationOutcome(
            lifecycle=MatchLifecycle.PLAYABLE,
            checkpoint_id=checkpoint_id,
            commit_checkpoint=commit,
        )


def _validate_restored_units(manifest: CheckpointManifest, state: GameState) -> None:
    battle = state.battle.value
    active = {
        slot.reference: slot.unit_type for slot in manifest.identity_metadata.slots if slot.active
    }
    if (
        state.frame != manifest.last_frame
        or battle is None
        or active != {unit.reference: unit.unit_type for unit in battle.units}
    ):
        raise CheckpointError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Restored state does not match the saved frame and unit identity ledger",
        )
