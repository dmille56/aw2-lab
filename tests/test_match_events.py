"""Bounded replay, atomic controller publication, and authorized event delivery."""

import asyncio
from uuid import uuid4

import pytest
from test_api_contract import summary
from test_authorized_match import command, prepare
from test_match_controller import IncrementingExecutor, run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab.api_contract import StateResponse, summary_from_controller
from aw2_lab.authorization import AuthorizationError
from aw2_lab.command_journal import JournalEvent
from aw2_lab.match_contract import CommandStatus, MatchLifecycle, PlayerSlot
from aw2_lab.match_controller import MatchControllerError
from aw2_lab.match_events import MatchEventPublisher


def state():
    return StateResponse(summary=summary_from_controller(summary()), settled=True, observation=None)


def changed(current, revision):
    return current.model_copy(
        update={"summary": current.summary.model_copy(update={"revision": revision})}
    )


@run_async_test
async def test_replay_cursors_and_atomic_snapshot_registration():
    publisher = MatchEventPublisher(replay_count=2)
    current = state()
    fresh = publisher.subscribe(current)
    snapshot = await fresh.next()
    assert snapshot.event.event == "snapshot" and snapshot.event.resync is False
    # No await separates registration from this publication.
    publisher.state_changed(current)
    first = await fresh.next()
    publisher.state_changed(changed(current, 1))
    second = await fresh.next()
    publisher.state_changed(changed(current, 2))
    third = await fresh.next()
    reconnect = publisher.subscribe(changed(current, 2), cursor=first.event.event_id)
    assert (await reconnect.next()).data == second.data
    assert (await reconnect.next()).data == third.data
    for cursor in (snapshot.event.event_id, "unknown", f"{uuid4()}:1"):
        stale = publisher.subscribe(changed(current, 2), cursor=cursor)
        resync = await stale.next()
        assert resync.event.event == "snapshot" and resync.event.resync is True
        assert resync.event.payload.summary.revision == 2
        stale.close()
    caught_up = publisher.subscribe(changed(current, 2), cursor=third.event.event_id)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await caught_up.next()
    for subscription in (fresh, reconnect, caught_up):
        subscription.close()


@pytest.mark.parametrize("limit", ["count", "bytes"])
@run_async_test
async def test_replay_bounds_and_slow_subscriber_limits(limit):
    current = state()
    publisher = MatchEventPublisher(
        replay_count=1 if limit == "count" else 256,
        replay_bytes=1 if limit == "bytes" else 1 << 20,
        subscriber_count=1 if limit == "count" else 128,
        subscriber_bytes=1 if limit == "bytes" else 1 << 20,
    )
    slow = publisher.subscribe(current)
    publisher.state_changed(current)
    publisher.state_changed(changed(current, 1))
    with pytest.raises(StopAsyncIteration):
        await slow.next()
    # The history itself respects the same count/byte limits.
    channel = publisher._channels[current.summary.match_id]
    assert len(channel.history) <= (1 if limit == "count" else 256)
    assert channel.history_bytes <= (1 if limit == "bytes" else 1 << 20)
    assert not channel.subscribers


@run_async_test
async def test_large_replay_resynchronizes_instead_of_overflowing_new_subscriber():
    publisher = MatchEventPublisher(subscriber_count=1)
    current = state()
    initial = publisher.subscribe(current)
    cursor = (await initial.next()).event.event_id
    initial.close()
    for revision in range(3):
        publisher.state_changed(changed(current, revision))
    reconnect = publisher.subscribe(changed(current, 2), cursor=cursor)
    event = (await reconnect.next()).event
    assert event.event == "snapshot" and event.resync is True
    reconnect.close()


@run_async_test
async def test_commands_publish_state_before_completion_and_revocation_drops_replay(
    memory, tmp_path
):
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingExecutor(IncrementingExecutor):
        async def execute(self, request, observation):
            entered.set()
            await release.wait()
            return await super().execute(request, observation)

    service, match_id, operator, player, other, _ = await prepare(
        memory, tmp_path, factory=BlockingExecutor
    )
    subscriptions = []
    try:
        for principal in (player, other, operator):
            subscription = await service.subscribe_events(principal, match_id)
            subscriptions.append(subscription)
            assert (await subscription.next()).event.payload.summary.revision == 1
        receipt = await service.submit(player, match_id, command(1))
        await entered.wait()
        # Subscription while a command executes sees the committed boundary.
        executing = await service.subscribe_events(other, match_id)
        subscriptions.append(executing)
        snapshot = (await executing.next()).event.payload
        assert snapshot.settled is False and snapshot.observation.revision == 1
        release.set()
        assert (
            await service.wait_for_command(operator, match_id, receipt.command_id, timeout=1)
        ).status is CommandStatus.COMPLETED
        for subscription in subscriptions[:3]:
            events = [(await subscription.next()).event for _ in range(5)]
            assert [event.event for event in events] == [
                "command.updated",
                "command.updated",
                "match.updated",
                "match.updated",
                "command.updated",
            ]
            assert [events[index].payload.status for index in (0, 1, 4)] == [
                CommandStatus.QUEUED,
                CommandStatus.RUNNING,
                CommandStatus.COMPLETED,
            ]
            assert events[2].payload.settled is False
            assert events[3].payload.summary.revision == events[4].payload.resulting_revision == 2
        pending = await service.subscribe_events(player, match_id)
        subscriptions.append(pending)
        await service.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
        with pytest.raises(AuthorizationError):
            await pending.next()
        with pytest.raises(AuthorizationError):
            await service.subscribe_events(player, match_id)
    finally:
        release.set()
        for subscription in subscriptions:
            subscription.close()
        await service.controller.stop()


@run_async_test
async def test_close_and_shutdown_end_subscriptions_and_closed_reconnects(memory, tmp_path):
    service, match_id, operator, player, _, _ = await prepare(memory, tmp_path)
    subscription = await service.subscribe_events(player, match_id)
    await subscription.next()
    receipt = await service.close(operator, match_id, uuid4())
    await service.wait_for_command(operator, match_id, receipt.command_id, timeout=1)
    events = [(await subscription.next()).event for _ in range(4)]
    assert events[-2].payload.summary.lifecycle is MatchLifecycle.CLOSED
    assert events[-1].payload.status is CommandStatus.COMPLETED
    with pytest.raises(StopAsyncIteration):
        await subscription.next()
    retained = await service.subscribe_events(player, match_id)
    assert (await retained.next()).event.payload.summary.lifecycle is MatchLifecycle.CLOSED
    with pytest.raises(StopAsyncIteration):
        await retained.next()
    retained.close()
    subscription.close()
    await service.controller.stop()
    with pytest.raises(MatchControllerError) as error:
        await service.subscribe_events(operator, match_id)
    assert error.value.body.code.value == "server_shutting_down"


@pytest.mark.parametrize(
    "status", [CommandStatus.COMPLETED, CommandStatus.ROLLED_BACK, CommandStatus.RECOVERY_REQUIRED]
)
@run_async_test
async def test_committed_state_is_not_sent_before_terminal_journal_write(
    memory, tmp_path, monkeypatch, status
):
    from dataclasses import replace

    class OutcomeExecutor(IncrementingExecutor):
        async def execute(self, request, observation):
            outcome = await super().execute(request, observation)
            lifecycle = (
                MatchLifecycle.RECOVERY_REQUIRED
                if status is CommandStatus.RECOVERY_REQUIRED
                else MatchLifecycle.PLAYABLE
            )
            return replace(outcome, status=status, lifecycle=lifecycle)

    service, match_id, operator, player, _, _ = await prepare(
        memory, tmp_path, factory=OutcomeExecutor
    )
    subscription = await service.subscribe_events(player, match_id)
    await subscription.next()
    reached, release = asyncio.Event(), asyncio.Event()
    journal = service.controller._journal
    append = journal.append

    async def gate(entry):
        if entry.event is JournalEvent.TERMINAL:
            reached.set()
            await release.wait()
        await append(entry)

    monkeypatch.setattr(journal, "append", gate)
    try:
        receipt = await service.submit(player, match_id, command(1))
        await reached.wait()
        first = [(await subscription.next()).event for _ in range(3)]
        assert first[-1].payload.summary.lifecycle is MatchLifecycle.EXECUTING
        with pytest.raises(TimeoutError):
            await subscription.next(timeout=0.01)
        release.set()
        await service.wait_for_command(operator, match_id, receipt.command_id, timeout=1)
        boundary = (await subscription.next()).event
        terminal = (await subscription.next()).event
        assert boundary.event == "match.updated"
        assert boundary.payload.summary.revision == 2
        assert terminal.event == "command.updated" and terminal.payload.status is status
    finally:
        release.set()
        subscription.close()
        await service.controller.stop()
