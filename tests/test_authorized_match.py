"""Principal checks at shared-service entry points, queue execution, and recovery."""

import asyncio
from uuid import uuid4

import pytest
from test_authorization import assert_code, token
from test_match_checkpoint import MemoryBridge
from test_match_controller import IncrementingExecutor, make_observation, run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export fixture

from aw2_lab.api_contract import (
    CreateMatchRequest,
    GameplayCommandRequest,
    IssueInvitationRequest,
    JoinSlotRequest,
)
from aw2_lab.authorization import AuthorizationError, AuthorizationService
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.command_journal import JsonlCommandJournal
from aw2_lab.match_checkpoint import CheckpointRuntime, CheckpointSession, MatchCheckpointService
from aw2_lab.match_contract import (
    CommandStatus,
    EndTurnAction,
    ErrorCode,
    MatchLifecycle,
    PlayerSlot,
    SlotStatus,
)
from aw2_lab.match_controller import MatchController, MutationOutcome
from aw2_lab.match_observation import MatchObservationTracker


async def prepare(memory, tmp_path, *, factory=IncrementingExecutor):
    auth = AuthorizationService(tmp_path / "authorization.json", token("o"))
    executor = factory(memory, None)
    controller = MatchController(
        authorization=auth,
        executor=executor,
        journal=JsonlCommandJournal(tmp_path / "commands.jsonl"),
    )
    service = AuthorizedMatchService(controller)
    await controller.start()
    operator = auth.authenticate(token("o"))
    summary = await service.create(operator, CreateMatchRequest(request_id=uuid4()))
    for slot, invitation, credential in (
        (PlayerSlot.SLOT_1, "i", "p"),
        (PlayerSlot.SLOT_2, "j", "q"),
    ):
        await service.invite(
            operator,
            summary.match_id,
            slot,
            IssueInvitationRequest(request_id=uuid4(), invitation_token=token(invitation)),
        )
        await service.join(
            summary.match_id,
            slot,
            token(credential),
            JoinSlotRequest(
                request_id=uuid4(), display_name="Player", invitation_token=token(invitation)
            ),
        )
    executor.tracker = MatchObservationTracker(summary.match_id)
    observation = make_observation(memory, summary.match_id, executor.tracker)
    receipt = await controller.activate_match(
        summary.match_id, observation, request_id=uuid4(), principal=operator
    )
    assert (
        await service.wait_for_command(operator, summary.match_id, receipt.command_id, timeout=1)
    ).status is CommandStatus.COMPLETED
    return (
        service,
        summary.match_id,
        operator,
        auth.authenticate(token("p")),
        auth.authenticate(token("q")),
        executor,
    )


def command(revision=1, request_id=None):
    return GameplayCommandRequest(
        request_id=request_id or uuid4(), expected_revision=revision, action=EndTurnAction()
    )


@run_async_test
async def test_entry_point_permissions_and_cached_receipt_revocation(memory, tmp_path):
    service, match_id, operator, player, other, executor = await prepare(memory, tmp_path)
    try:
        assert (await service.state(other, match_id)).observation is not None
        with pytest.raises(AuthorizationError) as caught:
            await service.close(player, match_id, uuid4())
        assert caught.value.body.code is ErrorCode.PERMISSION_DENIED
        with pytest.raises(AuthorizationError):
            await service.create(player, CreateMatchRequest(request_id=uuid4()))
        with pytest.raises(AuthorizationError):
            await service.submit(operator, match_id, command())
        request = command()
        receipt = await service.submit(player, match_id, request)
        assert (
            await service.wait_for_command(player, match_id, receipt.command_id, timeout=1)
        ).status is CommandStatus.COMPLETED
        assert (await service.submit(player, match_id, request)).command_id == receipt.command_id
        await service.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
        for action in (
            service.submit(player, match_id, request),
            service.command_status(player, match_id, receipt.command_id),
            service.state(player, match_id),
        ):
            with pytest.raises(AuthorizationError) as revoked:
                await action
            assert revoked.value.body.code is ErrorCode.INVALID_CREDENTIAL
        assert (await service.state(other, match_id)).summary.slots[0].status is SlotStatus.REVOKED
        assert executor.calls == 1
        journal = (tmp_path / "commands.jsonl").read_text()
        assert all(token(value).get_secret_value() not in journal for value in "oijpq")
    finally:
        await service.controller.stop()


@run_async_test
async def test_revoked_queued_work_rejected_running_work_finishes_and_wait_wakes(memory, tmp_path):
    class WaitingExecutor(IncrementingExecutor):
        def __init__(self, memory, tracker):
            super().__init__(memory, tracker)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def execute(self, request, observation):
            self.started.set()
            await self.release.wait()
            return await super().execute(request, observation)

    service, match_id, operator, player, _, executor = await prepare(
        memory, tmp_path, factory=WaitingExecutor
    )
    try:
        first = await service.submit(player, match_id, command())
        await executor.started.wait()
        second = await service.submit(player, match_id, command())
        wait = asyncio.create_task(
            service.wait_for_command(player, match_id, first.command_id, timeout=10)
        )
        await asyncio.sleep(0)
        await service.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
        with pytest.raises(AuthorizationError):
            await asyncio.wait_for(wait, 1)
        executor.release.set()
        completed = await service.wait_for_command(operator, match_id, first.command_id, timeout=1)
        rejected = await service.wait_for_command(operator, match_id, second.command_id, timeout=1)
        assert completed.status is CommandStatus.COMPLETED
        assert rejected.status is CommandStatus.REJECTED
        assert rejected.error.code is ErrorCode.INVALID_CREDENTIAL
        state = await service.state(operator, match_id)
        assert state.summary.revision == 2
        assert state.summary.slots[0].status is SlotStatus.REVOKED
        assert executor.calls == 1
    finally:
        executor.release.set()
        await service.controller.stop()


def checkpoints(controller, memory, tmp_path, tracker):
    bridge = MemoryBridge(memory)
    service = MatchCheckpointService(
        controller=controller,
        store=CheckpointStore(tmp_path / "checkpoints"),
        bridge=bridge,
        session=CheckpointSession(tracker, bridge.decoded),
        runtime=CheckpointRuntime(
            rom_sha256=memory[0].profile.sha256,
            emulator_build="synthetic-mgba",
            emulator_mode="headless",
        ),
    )
    return service, bridge


@run_async_test
async def test_checkpoint_roles_restore_and_restart_do_not_resurrect_revocation(memory, tmp_path):
    service, match_id, operator, player, other, executor = await prepare(memory, tmp_path)
    checkpoint, _ = checkpoints(service.controller, memory, tmp_path, executor.tracker)
    try:
        receipt = await checkpoint.create(match_id, player, request_id=uuid4(), expected_revision=1)
        saved = await service.wait_for_command(player, match_id, receipt.command_id, timeout=2)
        assert saved.status is CommandStatus.COMPLETED
        for action in (
            checkpoint.export(match_id, saved.checkpoint_id, player),
            checkpoint.import_archive(match_id, b"invalid", player),
            checkpoint.restore(
                match_id, saved.checkpoint_id, player, request_id=uuid4(), expected_revision=1
            ),
        ):
            with pytest.raises(AuthorizationError) as denied:
                await action
            assert denied.value.body.code is ErrorCode.PERMISSION_DENIED
        archive = await checkpoint.export(match_id, saved.checkpoint_id, operator)
        await service.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
        await checkpoint.import_archive(match_id, archive, operator)
        restored = await checkpoint.restore(
            match_id, saved.checkpoint_id, operator, request_id=uuid4(), expected_revision=1
        )
        assert (
            await service.wait_for_command(operator, match_id, restored.command_id, timeout=2)
        ).status is CommandStatus.COMPLETED
        assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: service.authenticate(token("p")))
        assert (await service.state(other, match_id)).summary.slots[0].status is SlotStatus.REVOKED
    finally:
        await service.controller.stop()
    restarted_auth = AuthorizationService(tmp_path / "authorization.json", token("o"))
    restarted = MatchController(authorization=restarted_auth)
    recovered, bridge = checkpoints(restarted, memory, tmp_path, MatchObservationTracker(match_id))
    await recovered.restore_startup_checkpoint(saved.checkpoint_id, durable_revision_floor=2)
    assert bridge.loads == 1
    assert (await restarted.inspect_match(match_id)).slots[0].status is SlotStatus.REVOKED
    assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: restarted_auth.authenticate(token("p")))
    # The same state cannot be adopted using authorization copied from its manifest.
    empty_auth = AuthorizationService(tmp_path / "missing.json", token("o"))
    empty = MatchController(authorization=empty_auth)
    rejected, untouched_bridge = checkpoints(
        empty, memory, tmp_path, MatchObservationTracker(match_id)
    )
    with pytest.raises(AuthorizationError) as missing:
        await rejected.restore_startup_checkpoint(saved.checkpoint_id, durable_revision_floor=2)
    assert missing.value.body.code is ErrorCode.RECOVERY_REQUIRED
    assert untouched_bridge.loads == untouched_bridge.release_calls == 0


@run_async_test
async def test_setup_restart_preserves_claim_and_requires_explicit_start(tmp_path):
    auth = AuthorizationService(tmp_path / "authorization.json", token("o"))
    controller = MatchController(authorization=auth)
    service = AuthorizedMatchService(controller)
    operator = auth.authenticate(token("o"))
    summary = await service.create(operator, CreateMatchRequest(request_id=uuid4()))
    await service.invite(
        operator,
        summary.match_id,
        PlayerSlot.SLOT_1,
        IssueInvitationRequest(request_id=uuid4(), invitation_token=token("i")),
    )
    request = JoinSlotRequest(
        request_id=uuid4(), display_name="Player", invitation_token=token("i")
    )
    await service.join(summary.match_id, PlayerSlot.SLOT_1, token("p"), request)
    restarted_auth = AuthorizationService(auth.path, token("o"))
    restarted = MatchController(authorization=restarted_auth)
    await restarted.recover_authorized_setup()
    public = AuthorizedMatchService(restarted)
    joined = await public.join(summary.match_id, PlayerSlot.SLOT_1, token("p"), request)
    assert joined.match.lifecycle is MatchLifecycle.SETUP
    assert (
        await public.state(restarted_auth.authenticate(token("p")), summary.match_id)
    ).observation is None
    with pytest.raises(AuthorizationError):
        await restarted.join_slot(summary.match_id, PlayerSlot.SLOT_2)


@run_async_test
async def test_operator_can_close_recovery_and_retained_state_stays_readable(memory, tmp_path):
    service, match_id, operator, player, _, _ = await prepare(memory, tmp_path)
    try:

        async def need_recovery():
            return MutationOutcome(
                status=CommandStatus.RECOVERY_REQUIRED, lifecycle=MatchLifecycle.RECOVERY_REQUIRED
            )

        receipt = await service.controller.submit_serialized_mutation(
            match_id=match_id,
            request_id=uuid4(),
            operation_name="test_recovery",
            payload={},
            expected_revision=1,
            mutates_emulator=False,
            principal=operator,
            handler=need_recovery,
        )
        await service.wait_for_command(operator, match_id, receipt.command_id, timeout=1)
        close = await service.close(operator, match_id, uuid4())
        assert (
            await service.wait_for_command(operator, match_id, close.command_id, timeout=1)
        ).status is CommandStatus.COMPLETED
        assert (await service.state(player, match_id)).summary.lifecycle is MatchLifecycle.CLOSED
        with pytest.raises(AuthorizationError):
            await service.submit(player, match_id, command())
    finally:
        await service.controller.stop()


@run_async_test
async def test_request_ids_cannot_cross_metadata_and_command_operations(memory, tmp_path):
    service, match_id, operator, player, _, _ = await prepare(memory, tmp_path)
    try:
        request = command()
        receipt = await service.submit(player, match_id, request)
        await service.wait_for_command(player, match_id, receipt.command_id, timeout=1)
        with pytest.raises(AuthorizationError) as conflict:
            await service.revoke(operator, match_id, PlayerSlot.SLOT_2, request.request_id)
        assert conflict.value.body.code is ErrorCode.REQUEST_ID_CONFLICT
        metadata_id = uuid4()
        await service.revoke(operator, match_id, PlayerSlot.SLOT_2, metadata_id)
        with pytest.raises(AuthorizationError) as conflict:
            await service.submit(player, match_id, command(revision=2, request_id=metadata_id))
        assert conflict.value.body.code is ErrorCode.REQUEST_ID_CONFLICT
    finally:
        await service.controller.stop()


@run_async_test
async def test_closed_checkpoint_does_not_reopen_on_application_recovery(memory, tmp_path):
    from types import SimpleNamespace

    from aw2_lab.api.app import _recover_checkpoint_on_startup
    from aw2_lab.emulator import EmulatorSettings

    service, match_id, operator, player, _, executor = await prepare(memory, tmp_path)
    checkpoint, _ = checkpoints(service.controller, memory, tmp_path, executor.tracker)
    receipt = await checkpoint.create(match_id, player, request_id=uuid4(), expected_revision=1)
    await service.wait_for_command(operator, match_id, receipt.command_id, timeout=2)
    close = await service.close(operator, match_id, uuid4())
    await service.wait_for_command(operator, match_id, close.command_id, timeout=1)
    await service.controller.stop()
    auth = AuthorizationService(tmp_path / "authorization.json", token("o"))
    restarted = MatchController(authorization=auth)
    assert (
        await _recover_checkpoint_on_startup(
            restarted,
            checkpoint.store,
            JsonlCommandJournal(tmp_path / "commands.jsonl"),
            SimpleNamespace(),
            EmulatorSettings(rom_path=tmp_path / "unused.gba"),
            memory[0].profile.sha256,
        )
        is None
    )
    await restarted.recover_authorized_setup()
    assert (await restarted.inspect_match(match_id)).lifecycle is MatchLifecycle.CLOSED


@pytest.mark.parametrize("with_checkpoint", [False, True])
@run_async_test
async def test_interrupted_close_reconciles_ledger_without_restoring_checkpoint(
    memory, tmp_path, with_checkpoint
):
    from types import SimpleNamespace

    from aw2_lab.api.app import _recover_checkpoint_on_startup
    from aw2_lab.command_journal import JournalEvent
    from aw2_lab.emulator import EmulatorSettings

    service, match_id, operator, player, _, executor = await prepare(memory, tmp_path)
    checkpoint, _ = checkpoints(service.controller, memory, tmp_path, executor.tracker)
    if with_checkpoint:
        saved = await checkpoint.create(match_id, player, request_id=uuid4(), expected_revision=1)
        await service.wait_for_command(operator, match_id, saved.command_id, timeout=2)
    request_id = uuid4()
    close = await service.close(operator, match_id, request_id)
    result = await service.wait_for_command(operator, match_id, close.command_id, timeout=1)
    await service.controller.stop()
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")
    # Reproduce a crash after the ledger rename but before the terminal append.
    entries = (await journal.read_entries()).entries
    journal.path.write_text(
        "".join(
            entry.model_dump_json() + "\n"
            for entry in entries
            if not (entry.command_id == close.command_id and entry.event is JournalEvent.TERMINAL)
        )
    )
    auth = AuthorizationService(tmp_path / "authorization.json", token("o"))
    restarted = MatchController(
        authorization=auth, journal=journal, checkpoint_store=checkpoint.store
    )
    # No bridge is supplied: recovery must not try to load the closed battlefield.
    for _ in range(2):
        assert (
            await _recover_checkpoint_on_startup(
                restarted,
                checkpoint.store,
                journal,
                SimpleNamespace(),
                EmulatorSettings(rom_path=tmp_path / "unused.gba"),
                memory[0].profile.sha256,
            )
            is None
        )
    terminals = [
        entry
        for entry in (await journal.read_entries()).entries
        if entry.command_id == close.command_id and entry.event is JournalEvent.TERMINAL
    ]
    assert len(terminals) == 1
    assert terminals[0].status is CommandStatus.COMPLETED
    assert terminals[0].resulting_revision == result.resulting_revision
    await restarted.recover_authorized_setup()
    await restarted.start()
    try:
        public = AuthorizedMatchService(restarted)
        current_operator = public.authenticate(token("o"))
        retry = await public.close(current_operator, match_id, request_id)
        assert retry.command_id == close.command_id
        assert await public.command_status(current_operator, match_id, retry.command_id) == result
        assert (await public.inspect(current_operator, match_id)).lifecycle is MatchLifecycle.CLOSED
        with pytest.raises(AuthorizationError):
            await public.close(operator, match_id, request_id)
    finally:
        await restarted.stop()


@run_async_test
async def test_operator_restore_retry_survives_restart_without_reexecution(memory, tmp_path):
    service, match_id, operator, player, _, executor = await prepare(memory, tmp_path)
    checkpoint, _ = checkpoints(service.controller, memory, tmp_path, executor.tracker)
    saved = await checkpoint.create(match_id, player, request_id=uuid4(), expected_revision=1)
    saved = await service.wait_for_command(operator, match_id, saved.command_id, timeout=2)
    request_id = uuid4()
    restore = await checkpoint.restore(
        match_id, saved.checkpoint_id, operator, request_id=request_id, expected_revision=1
    )
    result = await service.wait_for_command(operator, match_id, restore.command_id, timeout=2)
    assert result.status is CommandStatus.COMPLETED
    await service.controller.stop()
    auth = AuthorizationService(tmp_path / "authorization.json", token("o"))
    restarted = MatchController(
        authorization=auth,
        journal=JsonlCommandJournal(tmp_path / "commands.jsonl"),
        checkpoint_store=checkpoint.store,
    )
    recovered, bridge = checkpoints(restarted, memory, tmp_path, MatchObservationTracker(match_id))
    await recovered.restore_startup_checkpoint(result.checkpoint_id, durable_revision_floor=2)
    await restarted.start()
    try:
        current_operator = auth.authenticate(token("o"))
        loads = bridge.loads
        retry = await recovered.restore(
            match_id,
            saved.checkpoint_id,
            current_operator,
            request_id=request_id,
            expected_revision=1,
        )
        assert retry.command_id == restore.command_id
        assert await restarted.command_status(match_id, retry.command_id) == result
        assert bridge.loads == loads
        with pytest.raises(AuthorizationError) as stale:
            await recovered.restore(
                match_id, saved.checkpoint_id, operator, request_id=request_id, expected_revision=1
            )
        assert stale.value.body.code is ErrorCode.INVALID_CREDENTIAL
        from aw2_lab.match_controller import MatchControllerError

        with pytest.raises(MatchControllerError) as changed:
            await recovered.restore(
                match_id,
                saved.checkpoint_id,
                current_operator,
                request_id=request_id,
                expected_revision=2,
            )
        assert changed.value.body.code is ErrorCode.REQUEST_ID_CONFLICT
    finally:
        await restarted.stop()
