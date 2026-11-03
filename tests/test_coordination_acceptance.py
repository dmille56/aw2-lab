"""ROM-independent public coordination and commit-boundary restart acceptance."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_authorization import token
from test_http_gameplay_checkpoints import setup
from test_match_checkpoint import create, prepare
from test_match_controller import run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab import playable_runtime as runtime_module
from aw2_lab.api import app as app_module
from aw2_lab.command_journal import JournalEvent, JsonlCommandJournal
from aw2_lab.emulator import EmulatorSettings
from aw2_lab.match_contract import CommandStatus, EndTurnAction, ErrorCode, MatchLifecycle
from aw2_lab.match_controller import MatchController, MutationOutcome
from aw2_lab.sdk import APIError, AsyncAW2Client


@run_async_test
async def test_sdk_concurrent_duplicate_and_stale_submissions_execute_once(
    memory, tmp_path, monkeypatch
):
    app, runtime, _public, match_id, _operator, bridge = await setup(memory, tmp_path, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class Executor:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(runtime_module, "EndTurnActionExecutor", Executor)
    identifier = uuid4()
    try:
        async with (
            AsyncAW2Client(credential=token("p"), transport=httpx.ASGITransport(app=app)) as red,
            AsyncAW2Client(credential=token("q"), transport=httpx.ASGITransport(app=app)) as blue,
        ):
            first, duplicate = await asyncio.gather(
                *(red.submit(match_id, 1, EndTurnAction(), request_id=identifier) for _ in range(2))
            )
            assert first.command_id == duplicate.command_id
            await asyncio.wait_for(entered.wait(), 2)
            competing = await red.submit(match_id, 1, EndTurnAction())
            during = await blue.state(match_id)
            assert not during.settled and during.summary.revision == 1
            with pytest.raises(APIError) as conflict:
                await red.submit(match_id, 2, EndTurnAction(), request_id=identifier)
            assert conflict.value.response.error.code is ErrorCode.REQUEST_ID_CONFLICT
            release.set()
            for receipt in (first, competing):
                await runtime.controller.wait_for_command(match_id, receipt.command_id, timeout=2)
            success = await red.wait_for_command(match_id, first.command_id)
            stale = await red.wait_for_command(match_id, competing.command_id)
            assert success.status is CommandStatus.COMPLETED
            assert stale.status is CommandStatus.REJECTED
            assert stale.error.code is ErrorCode.STALE_REVISION
            assert stale.resulting_revision == success.resulting_revision == 2
            assert calls == 1
            wrong_turn = await blue.submit(match_id, 2, EndTurnAction())
            await runtime.controller.wait_for_command(match_id, wrong_turn.command_id, timeout=2)
            rejected = await blue.wait_for_command(match_id, wrong_turn.command_id)
            assert rejected.error.code is ErrorCode.NOT_YOUR_TURN
            assert calls == 1
            assert (await blue.state(match_id)).settled
    finally:
        release.set()
        await runtime.controller.stop()


@run_async_test
async def test_restart_after_current_commit_before_terminal_record_returns_committed_receipt(
    memory, tmp_path, monkeypatch
):
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")
    service, controller, match_id, credential, _, bridge = await prepare(
        memory, tmp_path, journal=journal
    )
    saved = await create(service, controller, match_id, credential)
    prior = await controller.current_observation(match_id)
    await controller.stop()
    # Model a crash after CURRENT replacement but before the final append reaches disk.
    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
    records = [
        record
        for record in records
        if not (record["command_id"] == str(saved.command_id) and record["event"] == "terminal")
    ]
    journal.path.write_text("".join(json.dumps(record) + "\n" for record in records))
    restarted = MatchController(journal=journal, checkpoint_store=service.store)

    async def observe(*args, **kwargs):
        return await bridge.decoded()

    monkeypatch.setattr(app_module, "capture_game_state", observe)
    try:
        recovered = await app_module._recover_checkpoint_on_startup(
            restarted,
            service.store,
            journal,
            SimpleNamespace(bridge=bridge, build_identity=service.runtime.emulator_build),
            EmulatorSettings(rom_path=tmp_path / "unused.gba"),
            memory[0].profile.sha256,
        )
        assert recovered is not None
        await restarted.start()
        result = await restarted.command_status(match_id, saved.command_id)
        assert result == saved
        assert (await restarted.current_observation(match_id)).revision > prior.revision
        assert (await restarted.current_observation(match_id)).game_state == prior.game_state
        saves_before = bridge.saves
        retried = await recovered.create(
            match_id,
            credential,
            request_id=saved.request_id,
            expected_revision=saved.accepted_revision,
        )
        assert retried.command_id == saved.command_id
        assert bridge.saves == saves_before
        entries = (await journal.read_entries()).entries
        assert (
            sum(
                e.command_id == saved.command_id and e.event is JournalEvent.TERMINAL
                for e in entries
            )
            == 1
        )
    finally:
        await restarted.stop()


@pytest.mark.parametrize("failure", ["unknown_menu", "frame_budget", "wall_watchdog"])
@run_async_test
async def test_navigation_unknown_menu_and_stalls_fail_with_bounded_diagnostics(memory, failure):
    from dataclasses import replace

    from test_state_validation import snapshot

    from aw2_lab.action_navigation import ActionNavigator, NavigationError, NavigationLimits
    from aw2_lab.state_decoder import decode_snapshot
    from aw2_lab.ui_state import MenuFamily

    state = decode_snapshot(snapshot(memory))
    state = replace(
        state,
        ui=replace(
            state.ui,
            menu=replace(
                state.ui.menu,
                family=MenuFamily.UNRESOLVED if failure == "unknown_menu" else MenuFamily.COMMAND,
                actionable=True,
            ),
        ),
    )
    calls = []

    class Bridge:
        async def advance_frames(self, frames):
            nonlocal state
            frame = state.frame + frames
            state = replace(
                state,
                frame=frame,
                validation=replace(state.validation, frame=frame),
                ui=replace(
                    state.ui,
                    frame=frame,
                    menu=replace(state.ui.menu, frame=frame),
                    map_cursor=replace(state.ui.map_cursor, frame=frame),
                ),
            )
            return state.frame

        async def press_keys(self, keys, frames):
            calls.append(keys)
            if failure == "wall_watchdog":
                await asyncio.Event().wait()
            return await self.advance_frames(frames)

    async def observe():
        return state

    navigator = ActionNavigator(
        Bridge(), observe, NavigationLimits(frame_budget=3, wall_timeout=0.02)
    )
    with pytest.raises(NavigationError) as caught:
        await asyncio.wait_for(navigator.confirm(lambda _: False, label="test"), 1)
    expected = {
        "unknown_menu": "recognized actionable menu",
        "frame_budget": "frame budget",
        "wall_watchdog": "watchdog",
    }[failure]
    assert expected in str(caught.value)
    assert caught.value.context.frame == state.frame
    if failure == "unknown_menu":
        assert calls == []


@pytest.mark.parametrize("failed_event", ["running", "terminal"])
@run_async_test
async def test_journal_failure_never_reports_public_gameplay_success(
    memory, tmp_path, monkeypatch, failed_event
):
    import errno

    app, runtime, _public, match_id, _operator, bridge = await setup(memory, tmp_path, monkeypatch)
    original_append = runtime.journal._append_sync
    calls = 0

    class Executor:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            nonlocal calls
            calls += 1
            bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    def fail(line):
        record = json.loads(line)
        if record["operation_name"] == "gameplay" and record["event"] == failed_event:
            raise OSError(errno.ENOSPC, "synthetic disk full")
        original_append(line)

    monkeypatch.setattr(runtime_module, "EndTurnActionExecutor", Executor)
    monkeypatch.setattr(runtime.journal, "_append_sync", fail)
    try:
        async with AsyncAW2Client(
            credential=token("p"), transport=httpx.ASGITransport(app=app)
        ) as red:
            receipt = await red.submit(match_id, 1, EndTurnAction())
            await runtime.controller.wait_for_command(match_id, receipt.command_id, timeout=2)
            result = await red.wait_for_command(match_id, receipt.command_id)
            assert result.status is CommandStatus.RECOVERY_REQUIRED
            assert not runtime.controller.queue_accepting
            assert calls == (0 if failed_event == "running" else 1)
            state = await red.state(match_id)
            assert state.summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED
            assert state.summary.revision == state.observation.revision == 1
    finally:
        await runtime.controller.stop()
