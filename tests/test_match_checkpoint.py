"""Authenticated, serialized checkpoint operations with a synthetic emulator."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from test_match_controller import run_async_test, setup_controller
from test_state_validation import memory as memory  # noqa: PLC0414
from test_state_validation import snapshot

from aw2_lab.checkpoint import CheckpointError
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.command_journal import JournalEvent
from aw2_lab.match_checkpoint import CheckpointRuntime, CheckpointSession, MatchCheckpointService
from aw2_lab.match_contract import CommandStatus, ErrorCode, MatchLifecycle
from aw2_lab.match_controller import MatchControllerError, MutationOutcome
from aw2_lab.state_decoder import decode_snapshot


class MemoryBridge:
    def __init__(self, memory):
        self.memory = memory
        self.frame = 123
        self.loads = 0
        self.saves = 0
        self.fail_load = False

    async def save_state_buffer_with_frame(self):
        self.saves += 1
        _, ewram, iwram = self.memory
        return self.frame.to_bytes(4, "little") + bytes(ewram) + bytes(iwram), self.frame

    async def load_state_buffer(self, state):
        from aw2_lab.bridge import BridgeError

        self.loads += 1
        if self.fail_load:
            raise BridgeError("synthetic emulator failure")
        self.frame = int.from_bytes(state[:4], "little")
        _, ewram, iwram = self.memory
        ewram[:] = state[4 : 4 + len(ewram)]
        iwram[:] = state[4 + len(ewram) :]
        return self.frame

    async def decoded(self):
        return decode_snapshot(replace(snapshot(self.memory), frame=self.frame))


class CapturingJournal:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)


async def prepare(memory, tmp_path, *, journal=None):
    controller, match_id, first, second, executor = await setup_controller(memory, journal=journal)
    bridge = MemoryBridge(memory)
    store = CheckpointStore(tmp_path / "checkpoints")
    service = MatchCheckpointService(
        controller=controller,
        store=store,
        bridge=bridge,
        session=CheckpointSession(executor.tracker, bridge.decoded),
        runtime=CheckpointRuntime(
            rom_sha256=memory[0].profile.sha256,
            emulator_build="synthetic-mgba",
            emulator_mode="headless",
        ),
    )
    return service, controller, match_id, SecretStr(first.credential), second, bridge


async def create(service, controller, match_id, credential):
    revision = (await controller.inspect_match(match_id)).revision
    receipt = await service.create(
        match_id, credential, request_id=uuid4(), expected_revision=revision
    )
    result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
    assert result.status is CommandStatus.COMPLETED
    return result


@run_async_test
async def test_create_move_restore_preserves_ids_and_credentials_with_fresh_revision(
    memory, tmp_path
):
    service, controller, match_id, credential, second, bridge = await prepare(memory, tmp_path)
    try:
        before = await controller.current_observation(match_id)
        saved = await create(service, controller, match_id, credential)
        assert saved.resulting_revision == before.revision
        assert bridge.saves == 1
        assert service.store.current().command_result == saved

        async def move():
            memory[1][0x22692] = 1
            bridge.frame += 1
            moved = service.session.tracker.commit_boundary(await bridge.decoded())
            return MutationOutcome(observation=moved, lifecycle=MatchLifecycle.PLAYABLE)

        moved = await controller.submit_serialized_mutation(
            match_id=match_id,
            request_id=uuid4(),
            operation_name="move_fixture",
            payload={},
            expected_revision=before.revision,
            handler=move,
        )
        await controller.wait_for_command(match_id, moved.command_id, timeout=2)
        assert bridge.saves == 2
        revision = (await controller.inspect_match(match_id)).revision
        receipt = await service.restore(
            match_id,
            saved.checkpoint_id,
            credential,
            request_id=uuid4(),
            expected_revision=revision,
        )
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        assert result.status is CommandStatus.COMPLETED
        after = await controller.current_observation(match_id)
        assert after.game_state == before.game_state
        assert after.unit_identities == before.unit_identities
        assert after.revision > revision
        assert service.session.tracker.read() == after
        assert service.store.current().command_result == result
        assert result.checkpoint_id != saved.checkpoint_id
        await controller.require_joined_credential(match_id, SecretStr(second.credential))
    finally:
        await controller.stop()


@run_async_test
async def test_mutation_persists_recovery_checkpoint_before_running(memory, tmp_path):
    journal = CapturingJournal()
    service, controller, match_id, _, _, bridge = await prepare(memory, tmp_path, journal=journal)
    try:
        before = await controller.current_observation(match_id)

        async def mutate():
            memory[1][0x22692] = 1
            bridge.frame += 1
            observation = service.session.tracker.commit_boundary(await bridge.decoded())
            return MutationOutcome(observation=observation, lifecycle=MatchLifecycle.PLAYABLE)

        receipt = await controller.submit_serialized_mutation(
            match_id=match_id,
            request_id=uuid4(),
            operation_name="test_mutation",
            payload={},
            expected_revision=before.revision,
            handler=mutate,
        )
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        running = next(
            entry
            for entry in journal.entries
            if entry.command_id == receipt.command_id and entry.event is JournalEvent.RUNNING
        )

        assert running.recovery_checkpoint_id is not None
        manifest, state = service.store.load(running.recovery_checkpoint_id)
        assert manifest.originating_command_id == receipt.command_id
        assert manifest.match.revision == before.revision
        assert manifest.last_frame == before.game_state.frame
        assert int.from_bytes(state[:4], "little") == before.game_state.frame
        assert result.status is CommandStatus.COMPLETED
        assert bridge.saves == 1
    finally:
        await controller.stop()


@run_async_test
async def test_create_retries_capture_once_and_exports_import_without_loading(memory, tmp_path):
    service, controller, match_id, credential, _, bridge = await prepare(memory, tmp_path)
    try:
        revision = (await controller.inspect_match(match_id)).revision
        request_id = uuid4()
        receipt = await service.create(
            match_id, credential, request_id=request_id, expected_revision=revision
        )
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        retry = await service.create(
            match_id, credential, request_id=request_id, expected_revision=revision
        )
        assert retry.command_id == receipt.command_id
        assert bridge.saves == 1
        exported = await service.export(match_id, result.checkpoint_id, credential)
        other_store = CheckpointStore(tmp_path / "imported")
        importer = MatchCheckpointService(
            controller=controller,
            store=other_store,
            bridge=bridge,
            session=service.session,
            runtime=service.runtime,
        )
        imported = await importer.import_archive(match_id, exported, credential)
        assert imported.checkpoint_id == result.checkpoint_id
        assert other_store.current() is None
        assert bridge.loads == 0
        assert (await controller.current_observation(match_id)).revision == revision
        with pytest.raises(MatchControllerError) as denied:
            await service.export(match_id, result.checkpoint_id, SecretStr("bad credential"))
        assert denied.value.body.code is ErrorCode.INVALID_CREDENTIAL
    finally:
        await controller.stop()


@run_async_test
async def test_incompatible_restore_rejected_before_emulator_mutation(memory, tmp_path):
    service, controller, match_id, credential, _, bridge = await prepare(memory, tmp_path)
    try:
        saved = await create(service, controller, match_id, credential)
        manifest, state = service.store.load(saved.checkpoint_id)
        incompatible = manifest.model_copy(
            update={"checkpoint_id": uuid4(), "emulator_build": "other"}
        )
        service.store.save(incompatible, state)
        revision = (await controller.inspect_match(match_id)).revision
        receipt = await service.restore(
            match_id,
            incompatible.checkpoint_id,
            credential,
            request_id=uuid4(),
            expected_revision=revision,
        )
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        assert result.status is CommandStatus.REJECTED
        assert result.error.code is ErrorCode.CHECKPOINT_INCOMPATIBLE
        assert bridge.loads == 0
        assert (await controller.inspect_match(match_id)).lifecycle is MatchLifecycle.PLAYABLE
    finally:
        await controller.stop()


@run_async_test
async def test_failed_restore_requires_recovery_and_successful_restore_unblocks(memory, tmp_path):
    service, controller, match_id, credential, _, bridge = await prepare(memory, tmp_path)
    try:
        before = await controller.current_observation(match_id)
        saved = await create(service, controller, match_id, credential)
        bridge.fail_load = True
        receipt = await service.restore(
            match_id,
            saved.checkpoint_id,
            credential,
            request_id=uuid4(),
            expected_revision=before.revision,
        )
        failure = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        assert failure.status is CommandStatus.RECOVERY_REQUIRED
        assert (
            await controller.inspect_match(match_id)
        ).lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        assert await controller.current_observation(match_id) is before
        assert not service.session.tracker.continuity_valid
        missing = await service.restore(
            match_id,
            uuid4(),
            credential,
            request_id=uuid4(),
            expected_revision=before.revision,
        )
        rejected = await controller.wait_for_command(match_id, missing.command_id, timeout=2)
        assert rejected.status is CommandStatus.REJECTED
        assert (
            await controller.inspect_match(match_id)
        ).lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        bridge.fail_load = False
        started, release = asyncio.Event(), asyncio.Event()
        original_load = bridge.load_state_buffer

        async def gated_load(state):
            started.set()
            await release.wait()
            return await original_load(state)

        bridge.load_state_buffer = gated_load
        receipt = await service.restore(
            match_id,
            saved.checkpoint_id,
            credential,
            request_id=uuid4(),
            expected_revision=before.revision,
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        assert (
            await controller.current_state(match_id)
        ).summary.lifecycle is MatchLifecycle.EXECUTING
        with pytest.raises(MatchControllerError) as unavailable:
            await controller.current_observation(match_id)
        assert unavailable.value.body.code is ErrorCode.OBSERVATION_UNAVAILABLE
        release.set()
        restored = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        assert restored.status is CommandStatus.COMPLETED
        assert (await controller.inspect_match(match_id)).lifecycle is MatchLifecycle.PLAYABLE
    finally:
        await controller.stop()


@run_async_test
async def test_current_is_durable_before_terminal_journal_event(memory, tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    observed = []

    class CheckingJournal:
        async def append(self, entry):
            if entry.event is JournalEvent.TERMINAL and entry.checkpoint_id is not None:
                pointer = store.current()
                assert pointer.checkpoint_id == entry.checkpoint_id
                assert pointer.command_result.command_id == entry.command_id
                observed.append(entry)

    service, controller, match_id, credential, _, _ = await prepare(
        memory, tmp_path, journal=CheckingJournal()
    )
    try:
        result = await create(service, controller, match_id, credential)
        assert len(observed) == 1
        assert observed[0].checkpoint_id == result.checkpoint_id
    finally:
        await controller.stop()


@run_async_test
async def test_commit_failure_does_not_report_success_or_publish_restored_state(
    memory, tmp_path, monkeypatch
):
    service, controller, match_id, credential, _, _ = await prepare(memory, tmp_path)
    try:
        saved = await create(service, controller, match_id, credential)
        before = await controller.current_observation(match_id)

        def fail(*args, **kwargs):
            raise CheckpointError(ErrorCode.STORAGE_UNAVAILABLE, "synthetic storage failure")

        monkeypatch.setattr(service.store, "commit", fail)
        receipt = await service.restore(
            match_id,
            saved.checkpoint_id,
            credential,
            request_id=uuid4(),
            expected_revision=before.revision,
        )
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        assert result.status is CommandStatus.RECOVERY_REQUIRED
        assert await controller.current_observation(match_id) is before
        assert (
            await controller.inspect_match(match_id)
        ).lifecycle is MatchLifecycle.RECOVERY_REQUIRED
    finally:
        await controller.stop()


@run_async_test
async def test_import_rejects_foreign_match_without_loading_or_changing_current(memory, tmp_path):
    service, controller, match_id, credential, _, bridge = await prepare(memory, tmp_path)
    try:
        saved = await create(service, controller, match_id, credential)
        original_pointer = service.store.current()
        manifest, state = service.store.load(saved.checkpoint_id)
        foreign = manifest.model_copy(
            update={
                "checkpoint_id": uuid4(),
                "match": manifest.match.model_copy(update={"match_id": uuid4()}),
            }
        )
        transfer = CheckpointStore(tmp_path / "foreign")
        transfer.save(foreign, state)
        archive = transfer.export_archive(foreign.checkpoint_id)
        with pytest.raises(CheckpointError) as failure:
            await service.import_archive(match_id, archive, credential)
        assert failure.value.body.code is ErrorCode.CHECKPOINT_INCOMPATIBLE
        assert service.store.current() == original_pointer
        assert not (service.store.root / str(foreign.checkpoint_id)).exists()
        assert bridge.loads == 0
    finally:
        await controller.stop()


@run_async_test
async def test_restore_rejects_unit_ledger_disagreement_without_publishing_new_ids(
    memory, tmp_path
):
    service, controller, match_id, credential, _, _ = await prepare(memory, tmp_path)
    try:
        saved = await create(service, controller, match_id, credential)
        before = await controller.current_observation(match_id)
        manifest, state = service.store.load(saved.checkpoint_id)
        slots = list(manifest.identity_metadata.slots)
        slots[0] = slots[0].model_copy(update={"unit_type": 2})
        changed = manifest.model_copy(
            update={
                "checkpoint_id": uuid4(),
                "identity_metadata": manifest.identity_metadata.model_copy(
                    update={"slots": tuple(slots)}
                ),
            }
        )
        service.store.save(changed, state)
        receipt = await service.restore(
            match_id,
            changed.checkpoint_id,
            credential,
            request_id=uuid4(),
            expected_revision=before.revision,
        )
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=2)
        assert result.status is CommandStatus.RECOVERY_REQUIRED
        assert result.error.details["failure_code"] == "checkpoint_corrupt"
        assert await controller.current_observation(match_id) is before
    finally:
        await controller.stop()
