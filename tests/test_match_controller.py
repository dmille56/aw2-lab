"""ROM-independent tests for the serialized match controller."""

import asyncio
from dataclasses import replace
from functools import wraps
from uuid import uuid4

import pytest
from pydantic import SecretStr
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.match_contract import (
    CommandRequest,
    CommandStatus,
    EndTurnAction,
    ErrorCode,
    MatchLifecycle,
    PlayerSlot,
)
from aw2_lab.match_controller import (
    MatchController,
    MatchControllerError,
    MutationOutcome,
)
from aw2_lab.match_observation import MatchObservation, MatchObservationTracker
from aw2_lab.state_decoder import decode_snapshot


def run_async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        asyncio.run(function(*args, **kwargs))

    return wrapper


def make_observation(memory, match_id, tracker, frame: int = 123) -> MatchObservation:
    assert tracker.match_id == match_id
    state = decode_snapshot(replace(snapshot(memory), frame=frame))
    return tracker.commit_boundary(state)


class IncrementingExecutor:
    def __init__(self, memory, tracker: MatchObservationTracker | None) -> None:
        self.memory = memory
        self.tracker = tracker
        self.calls = 0

    async def execute(self, request, observation) -> MutationOutcome:
        self.calls += 1
        assert self.tracker is not None
        state = decode_snapshot(
            replace(snapshot(self.memory), frame=observation.game_state.frame + 1)
        )
        committed = self.tracker.commit_boundary(state)
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)


async def setup_controller(memory, *, executor_factory=IncrementingExecutor, **options):
    executor = executor_factory(memory, None)
    match = MatchController(executor=executor, **options)
    await match.start()
    summary = await match.create_match()
    slot_1 = await match.join_slot(summary.match_id, PlayerSlot.SLOT_1, display_name="one")
    slot_2 = await match.join_slot(summary.match_id, PlayerSlot.SLOT_2, display_name="two")
    # The ledger's match identity must be the controller-generated match ID.
    executor.tracker = MatchObservationTracker(summary.match_id)
    observation = make_observation(memory, summary.match_id, executor.tracker)
    activation = await match.activate_match(
        summary.match_id,
        observation,
        request_id=uuid4(),
    )
    activated = await match.wait_for_command(summary.match_id, activation.command_id, timeout=1)
    assert activated.status is CommandStatus.COMPLETED
    return match, summary.match_id, slot_1, slot_2, executor


def make_command(match_id, player, revision):
    return CommandRequest(
        match_id=match_id,
        player_slot=player.player_slot,
        credential=SecretStr(player.credential),
        request_id=uuid4(),
        expected_revision=revision,
        action=EndTurnAction(),
    )


@run_async_test
async def test_match_lifecycle_ownership_and_private_credentials(memory) -> None:
    controller = MatchController()
    await controller.start()
    summary = await controller.create_match()
    assert summary.lifecycle is MatchLifecycle.SETUP
    assert summary.configuration.map_id == "bean_island"
    with pytest.raises(MatchControllerError) as active:
        await controller.create_match()
    assert active.value.body.code is ErrorCode.ACTIVE_MATCH_EXISTS

    slot_1 = await controller.join_slot(summary.match_id, PlayerSlot.SLOT_1)
    assert len(slot_1.credential) >= 32
    assert "credential" not in (await controller.inspect_match(summary.match_id)).model_dump_json()
    with pytest.raises(MatchControllerError) as error:
        await controller.join_slot(summary.match_id, PlayerSlot.SLOT_1)
    assert error.value.body.code is ErrorCode.SLOT_UNAVAILABLE
    close_receipt = await controller.close_match(
        summary.match_id,
        SecretStr(slot_1.credential),
        request_id=uuid4(),
    )
    closed = await controller.wait_for_command(
        summary.match_id, close_receipt.command_id, timeout=1
    )
    assert closed.status is CommandStatus.COMPLETED
    assert (await controller.inspect_match(summary.match_id)).lifecycle is MatchLifecycle.CLOSED
    assert (await controller.create_match()).match_id != summary.match_id
    await controller.stop()


@run_async_test
async def test_commands_are_idempotent_and_execute_once(memory) -> None:
    controller, match_id, slot_1, _, executor = await setup_controller(memory)
    observation = await controller.current_observation(match_id)
    request_id = uuid4()
    request = CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr(slot_1.credential),
        request_id=request_id,
        expected_revision=observation.revision,
        action=EndTurnAction(),
    )

    first = await controller.submit_command(request)
    retry = await controller.submit_command(
        request.model_copy(update={"credential": SecretStr("another-secret-token-1234567890")})
    )
    assert retry.command_id == first.command_id
    result = await controller.wait_for_command(match_id, first.command_id, timeout=1)
    assert result.status is CommandStatus.COMPLETED
    assert result.resulting_revision == observation.revision + 1
    assert executor.calls == 1

    with pytest.raises(MatchControllerError) as conflict:
        await controller.submit_command(
            request.model_copy(update={"expected_revision": observation.revision + 1})
        )
    assert conflict.value.body.code is ErrorCode.REQUEST_ID_CONFLICT
    await controller.stop()


@run_async_test
async def test_stale_revision_and_wrong_turn_are_rejected_at_execution(memory) -> None:
    controller, match_id, slot_1, slot_2, _ = await setup_controller(memory)
    observation = await controller.current_observation(match_id)

    stale = CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_1,
        credential=SecretStr(slot_1.credential),
        request_id=uuid4(),
        expected_revision=observation.revision - 1,
        action=EndTurnAction(),
    )
    stale_receipt = await controller.submit_command(stale)
    stale_result = await controller.wait_for_command(match_id, stale_receipt.command_id, timeout=1)
    assert stale_result.status is CommandStatus.REJECTED
    assert stale_result.resulting_revision == observation.revision
    assert stale_result.error is not None
    assert stale_result.error.code is ErrorCode.STALE_REVISION

    wrong_turn = CommandRequest(
        match_id=match_id,
        player_slot=PlayerSlot.SLOT_2,
        credential=SecretStr(slot_2.credential),
        request_id=uuid4(),
        expected_revision=observation.revision,
        action=EndTurnAction(),
    )
    wrong_turn_receipt = await controller.submit_command(wrong_turn)
    wrong_turn_result = await controller.wait_for_command(
        match_id, wrong_turn_receipt.command_id, timeout=1
    )
    assert wrong_turn_result.status is CommandStatus.REJECTED
    assert wrong_turn_result.resulting_revision == observation.revision
    assert wrong_turn_result.error is not None
    assert wrong_turn_result.error.code is ErrorCode.NOT_YOUR_TURN
    assert (await controller.inspect_match(match_id)).lifecycle is MatchLifecycle.PLAYABLE
    await controller.stop()


@run_async_test
async def test_internal_emulator_mutations_share_queue_and_revision_checks(memory) -> None:
    controller, match_id, _, _, executor = await setup_controller(memory)
    before = await controller.current_observation(match_id)

    async def debug_frame_step() -> MutationOutcome:
        assert executor.tracker is not None
        next_state = decode_snapshot(replace(snapshot(memory), frame=before.game_state.frame + 1))
        observation = executor.tracker.commit_boundary(next_state)
        return MutationOutcome(observation=observation, lifecycle=MatchLifecycle.PLAYABLE)

    receipt = await controller.submit_serialized_mutation(
        match_id=match_id,
        request_id=uuid4(),
        operation_name="debug_frame_step",
        payload={"frames": 1},
        expected_revision=before.revision,
        handler=debug_frame_step,
    )
    result = await controller.wait_for_command(match_id, receipt.command_id, timeout=1)
    assert result.status is CommandStatus.COMPLETED
    assert result.resulting_revision == before.revision + 1
    assert (await controller.current_observation(match_id)).revision == before.revision + 1
    await controller.stop()


@run_async_test
async def test_queue_backpressure_and_client_wait_timeout_do_not_cancel_work(memory) -> None:
    gate = asyncio.Event()

    class WaitingExecutor(IncrementingExecutor):
        def __init__(self, memory, tracker) -> None:
            super().__init__(memory, tracker)
            self.started = asyncio.Event()

        async def execute(self, request, observation) -> MutationOutcome:
            self.started.set()
            await gate.wait()
            return await super().execute(request, observation)

    tracker = MatchObservationTracker(uuid4())
    executor = WaitingExecutor(memory, tracker)
    controller = MatchController(executor=executor, queue_capacity=1, command_capacity=4)
    await controller.start()
    summary = await controller.create_match()
    first_slot = await controller.join_slot(summary.match_id, PlayerSlot.SLOT_1)
    await controller.join_slot(summary.match_id, PlayerSlot.SLOT_2)
    tracker = MatchObservationTracker(summary.match_id)
    executor.tracker = tracker
    observation = make_observation(memory, summary.match_id, tracker)
    receipt = await controller.activate_match(summary.match_id, observation, request_id=uuid4())
    await controller.wait_for_command(summary.match_id, receipt.command_id, timeout=1)
    state = await controller.current_observation(summary.match_id)

    def command(request_id):
        return CommandRequest(
            match_id=summary.match_id,
            player_slot=PlayerSlot.SLOT_1,
            credential=SecretStr(first_slot.credential),
            request_id=request_id,
            expected_revision=state.revision,
            action=EndTurnAction(),
        )

    first = await controller.submit_command(command(uuid4()))
    await executor.started.wait()
    with pytest.raises(MatchControllerError) as timeout_error:
        await controller.wait_for_command(summary.match_id, first.command_id, timeout=0.01)
    assert timeout_error.value.body.code is ErrorCode.TIMEOUT
    queued = await controller.submit_command(command(uuid4()))
    with pytest.raises(MatchControllerError) as full:
        await controller.submit_command(command(uuid4()))
    assert full.value.body.code is ErrorCode.COMMAND_CAPACITY

    gate.set()
    await controller.wait_for_command(summary.match_id, first.command_id, timeout=1)
    await controller.wait_for_command(summary.match_id, queued.command_id, timeout=1)
    await controller.stop()


@run_async_test
async def test_shutdown_marks_running_and_pending_commands(memory) -> None:
    gate = asyncio.Event()

    class StuckExecutor(IncrementingExecutor):
        def __init__(self, memory, tracker) -> None:
            super().__init__(memory, tracker)
            self.started = asyncio.Event()

        async def execute(self, request, observation) -> MutationOutcome:
            self.started.set()
            await gate.wait()
            return await super().execute(request, observation)

    executor = StuckExecutor(memory, None)
    controller = MatchController(
        executor=executor,
        queue_capacity=2,
        command_capacity=4,
        shutdown_timeout=0.01,
    )
    await controller.start()
    summary = await controller.create_match()
    slot_1 = await controller.join_slot(summary.match_id, PlayerSlot.SLOT_1)
    await controller.join_slot(summary.match_id, PlayerSlot.SLOT_2)
    executor.tracker = MatchObservationTracker(summary.match_id)
    observation = make_observation(memory, summary.match_id, executor.tracker)
    activation = await controller.activate_match(summary.match_id, observation, request_id=uuid4())
    await controller.wait_for_command(summary.match_id, activation.command_id, timeout=1)

    def command():
        return CommandRequest(
            match_id=summary.match_id,
            player_slot=PlayerSlot.SLOT_1,
            credential=SecretStr(slot_1.credential),
            request_id=uuid4(),
            expected_revision=observation.revision,
            action=EndTurnAction(),
        )

    running = await controller.submit_command(command())
    await executor.started.wait()
    pending = await controller.submit_command(command())
    await controller.stop()

    running_result = await controller.command_status(summary.match_id, running.command_id)
    pending_result = await controller.command_status(summary.match_id, pending.command_id)
    assert running_result.status is CommandStatus.RECOVERY_REQUIRED
    assert pending_result.status is CommandStatus.REJECTED
    assert pending_result.error is not None
    assert pending_result.error.code is ErrorCode.SERVER_SHUTTING_DOWN


@run_async_test
async def test_gameplay_without_observation_requires_recovery(memory) -> None:
    class EmptyOutcomeExecutor(IncrementingExecutor):
        async def execute(self, request, observation) -> MutationOutcome:
            return MutationOutcome()

    controller, match_id, player, _, _ = await setup_controller(
        memory, executor_factory=EmptyOutcomeExecutor
    )
    try:
        before = await controller.current_observation(match_id)
        receipt = await controller.submit_command(make_command(match_id, player, before.revision))
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=1)

        assert result.status is CommandStatus.RECOVERY_REQUIRED
        assert result.resulting_revision == before.revision
        summary = await controller.inspect_match(match_id)
        assert summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        assert summary.revision == before.revision
        assert await controller.current_observation(match_id) is before
    finally:
        await controller.stop()


@pytest.mark.parametrize(
    ("lifecycle", "status"),
    [
        (MatchLifecycle.SETUP, CommandStatus.COMPLETED),
        (MatchLifecycle.RECOVERY_REQUIRED, CommandStatus.COMPLETED),
        (MatchLifecycle.FINISHED, CommandStatus.ROLLED_BACK),
    ],
)
@run_async_test
async def test_invalid_outcome_preserves_committed_observation(memory, lifecycle, status) -> None:
    class InvalidOutcomeExecutor(IncrementingExecutor):
        async def execute(self, request, observation) -> MutationOutcome:
            next_outcome = await super().execute(request, observation)
            return MutationOutcome(
                observation=next_outcome.observation, lifecycle=lifecycle, status=status
            )

    controller, match_id, player, _, _ = await setup_controller(
        memory, executor_factory=InvalidOutcomeExecutor
    )
    try:
        before = await controller.current_observation(match_id)
        receipt = await controller.submit_command(make_command(match_id, player, before.revision))
        result = await controller.wait_for_command(match_id, receipt.command_id, timeout=1)

        assert result.status is CommandStatus.RECOVERY_REQUIRED
        summary = await controller.inspect_match(match_id)
        assert summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        assert summary.revision == before.revision
        assert await controller.current_observation(match_id) is before
    finally:
        await controller.stop()


@run_async_test
async def test_forced_shutdown_exits_when_executor_catches_cancellation(memory) -> None:
    class CatchCancellationExecutor(IncrementingExecutor):
        def __init__(self, memory, tracker) -> None:
            super().__init__(memory, tracker)
            self.started = asyncio.Event()

        async def execute(self, request, observation) -> MutationOutcome:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return await super().execute(request, observation)

    controller, match_id, player, _, executor = await setup_controller(
        memory,
        executor_factory=CatchCancellationExecutor,
        shutdown_timeout=0.01,
        shutdown_cancel_timeout=0.1,
    )
    before = await controller.current_observation(match_id)
    running = await controller.submit_command(make_command(match_id, player, before.revision))
    await executor.started.wait()
    pending = await controller.submit_command(make_command(match_id, player, before.revision))
    stopping = asyncio.create_task(controller.stop())
    try:
        done, _ = await asyncio.wait({stopping}, timeout=1)
        assert stopping in done, "Shutdown hung after the executor caught cancellation"
        await stopping
        running_result = await controller.command_status(match_id, running.command_id)
        pending_result = await controller.command_status(match_id, pending.command_id)
        assert running_result.status is CommandStatus.RECOVERY_REQUIRED
        assert pending_result.status is CommandStatus.REJECTED
        assert pending_result.error.code is ErrorCode.SERVER_SHUTTING_DOWN
        assert (await controller.inspect_match(match_id)).revision == before.revision
        assert await controller.current_observation(match_id) is before
    finally:
        if not stopping.done():
            stopping.cancel()
            await asyncio.gather(stopping, return_exceptions=True)


@run_async_test
async def test_shutdown_reports_cancellation_deadline_and_ignores_late_outcome(memory) -> None:
    release = asyncio.Event()

    class SlowCancellationExecutor(IncrementingExecutor):
        def __init__(self, memory, tracker) -> None:
            super().__init__(memory, tracker)
            self.started = asyncio.Event()
            self.finished = asyncio.Event()

        async def execute(self, request, observation) -> MutationOutcome:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                try:
                    return await super().execute(request, observation)
                finally:
                    self.finished.set()

    controller, match_id, player, _, executor = await setup_controller(
        memory,
        executor_factory=SlowCancellationExecutor,
        shutdown_timeout=0.01,
        shutdown_cancel_timeout=0.01,
    )
    before = await controller.current_observation(match_id)
    running = await controller.submit_command(make_command(match_id, player, before.revision))
    await executor.started.wait()
    pending = await controller.submit_command(make_command(match_id, player, before.revision))
    try:
        with pytest.raises(MatchControllerError, match="cancellation deadline") as error:
            await controller.stop()
        assert error.value.body.code is ErrorCode.RECOVERY_REQUIRED
        assert (await controller.command_status(match_id, running.command_id)).status is (
            CommandStatus.RECOVERY_REQUIRED
        )
        assert (await controller.command_status(match_id, pending.command_id)).status is (
            CommandStatus.REJECTED
        )
    finally:
        release.set()
        await asyncio.wait_for(executor.finished.wait(), timeout=1)

    assert await controller.current_observation(match_id) is before
    summary = await controller.inspect_match(match_id)
    assert summary.revision == before.revision
    assert summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED
    assert (await controller.command_status(match_id, running.command_id)).status is (
        CommandStatus.RECOVERY_REQUIRED
    )
