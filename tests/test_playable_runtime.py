"""Runtime composition, queue ownership, persistence, and tracker replacement."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_authorization import token
from test_match_checkpoint import MemoryBridge
from test_match_controller import run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab.action_navigation import InputEvent
from aw2_lab.api_contract import (
    CreateMatchRequest,
    GameplayCommandRequest,
    IssueInvitationRequest,
    JoinSlotRequest,
    StartMatchRequest,
)
from aw2_lab.authorization import AuthorizationError, AuthorizationService
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.bridge import MemorySnapshot
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.cold_boot import ColdBootResult
from aw2_lab.command_journal import JsonlCommandJournal
from aw2_lab.match_contract import CommandStatus, ErrorCode, MatchLifecycle, PlayerSlot
from aw2_lab.match_controller import MatchController, MutationOutcome
from aw2_lab.playable_runtime import PlayableRuntime


class RuntimeBridge(MemoryBridge):
    async def press_keys(self, keys, frames):
        self.keys = keys
        self.frame += frames
        self.keys = 0
        return self.frame

    async def advance_frames(self, frames):
        self.frame += frames
        return self.frame

    async def reset(self):
        self.resets = getattr(self, "resets", 0) + 1
        self.frame = 0
        return 0

    async def read_memory_snapshot(self, ranges):
        _, ewram, iwram = self.memory
        values = []
        for address, length in ranges:
            if 0x02000000 <= address and address + length <= 0x02040000:
                values.append(bytes(ewram[address - 0x02000000 : address - 0x02000000 + length]))
            elif 0x03000000 <= address and address + length <= 0x03008000:
                values.append(bytes(iwram[address - 0x03000000 : address - 0x03000000 + length]))
            else:
                raise ValueError("synthetic memory read is outside work RAM")
        return MemorySnapshot(frame=self.frame, ranges=tuple(values))

    async def request(self, operation, **payload):
        if operation != "write_memory":
            raise ValueError(f"unsupported synthetic bridge operation: {operation}")
        address = payload["address"]
        values = bytes(payload["bytes"])
        _, ewram, iwram = self.memory
        if 0x02000000 <= address and address + len(values) <= 0x02040000:
            target, offset = ewram, address - 0x02000000
        elif 0x03000000 <= address and address + len(values) <= 0x03008000:
            target, offset = iwram, address - 0x03000000
        else:
            raise ValueError("synthetic memory write is outside work RAM")
        target[offset : offset + len(values)] = values
        return {"written": len(values)}


async def setup(memory, tmp_path, *, joins=2, boot=None):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")
    store = CheckpointStore(tmp_path / "checkpoints")
    controller = MatchController(authorization=auth, journal=journal, checkpoint_store=store)
    bridge = RuntimeBridge(memory)

    async def boot_match(*args, **kwargs):
        bridge.boot_calls = getattr(bridge, "boot_calls", 0) + 1
        if boot is not None:
            await boot()
        bridge.frame = 123
        return ColdBootResult(await bridge.decoded(), 1, ())

    runtime = PlayableRuntime(
        controller=controller,
        bridge=bridge,
        rom_path=tmp_path / "rom.gba",
        rom_sha256=memory[0].profile.sha256,
        emulator_build="synthetic-mgba",
        emulator_mode="headless",
        store=store,
        journal=journal,
        boot_match=boot_match,
        observe=bridge.decoded,
    )
    public = AuthorizedMatchService(controller)
    await controller.start()
    operator = public.authenticate(token("o"))
    match = await public.create(operator, CreateMatchRequest(request_id=uuid4()))
    for index, slot in enumerate(PlayerSlot):
        if index >= joins:
            break
        await public.invite(
            operator,
            match.match_id,
            slot,
            IssueInvitationRequest(request_id=uuid4(), invitation_token=token("ij"[index])),
        )
        await public.join(
            match.match_id,
            slot,
            token("pq"[index]),
            JoinSlotRequest(
                request_id=uuid4(), display_name="Player", invitation_token=token("ij"[index])
            ),
        )
    return runtime, public, match.match_id, operator, bridge


def start_request():
    return StartMatchRequest(request_id=uuid4(), expected_revision=0)


@run_async_test
async def test_start_is_queued_idempotent_and_commits_initial_checkpoint(memory, tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    async def boot():
        entered.set()
        await release.wait()

    runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, boot=boot)
    try:
        request = start_request()
        receipt = await public.start(operator, match_id, request)
        await asyncio.wait_for(entered.wait(), 1)
        state = await public.state(operator, match_id)
        assert state.summary.lifecycle is MatchLifecycle.EXECUTING
        assert state.observation is None and not state.settled
        assert (await public.start(operator, match_id, request)).command_id == receipt.command_id
        # A second distinct request is accepted but must fail before any second reset.
        second = await public.start(operator, match_id, start_request())
        release.set()
        result = await public.wait_for_command(operator, match_id, receipt.command_id, timeout=2)
        rejected = await public.wait_for_command(operator, match_id, second.command_id, timeout=2)
        assert result.status is CommandStatus.COMPLETED
        assert result.resulting_revision == 1 and result.checkpoint_id is not None
        assert rejected.status is CommandStatus.REJECTED
        assert bridge.resets == bridge.boot_calls == 1
        assert runtime.store.current().command_result == result
        assert (
            await public.state(operator, match_id)
        ).observation == runtime.checkpoints.session.tracker.read()
    finally:
        release.set()
        await public.controller.stop()


@run_async_test
async def test_start_requires_operator_and_both_claims_before_input(memory, tmp_path):
    runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, joins=1)
    try:
        with pytest.raises(AuthorizationError):
            await public.start(public.authenticate(token("p")), match_id, start_request())
        receipt = await public.start(operator, match_id, start_request())
        result = await public.wait_for_command(operator, match_id, receipt.command_id, timeout=1)
        assert result.status is CommandStatus.REJECTED
        assert result.error.code is ErrorCode.SLOT_UNAVAILABLE
        assert not hasattr(bridge, "resets")
        assert runtime.store.current() is None
    finally:
        await public.controller.stop()


@run_async_test
async def test_failed_boot_is_recovery_required_without_playable_publication(memory, tmp_path):
    async def fail():
        raise RuntimeError("unexpected menu")

    runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, boot=fail)
    try:
        receipt = await public.start(operator, match_id, start_request())
        result = await public.wait_for_command(operator, match_id, receipt.command_id, timeout=2)
        state = await public.state(operator, match_id)
        assert result.status is CommandStatus.RECOVERY_REQUIRED
        assert state.summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        assert state.observation is None and state.summary.revision == 0
        assert bridge.keys == 0 and runtime.store.current() is None
        assert public.authorization.summaries()[0].lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        close = await public.close(operator, match_id, uuid4())
        assert (
            await public.wait_for_command(operator, match_id, close.command_id, timeout=1)
        ).status is CommandStatus.COMPLETED
    finally:
        await public.controller.stop()


@pytest.mark.parametrize(
    "kind,executor_name,extra",
    [
        ("move_wait", "MoveWaitActionExecutor", {"unit_id": "1", "path": []}),
        (
            "move_attack",
            "MoveAttackActionExecutor",
            {"unit_id": "1", "path": [], "target": {"x": 1, "y": 1}},
        ),
        ("move_capture", "MoveCaptureActionExecutor", {"unit_id": "1", "path": []}),
        (
            "purchase",
            "PurchaseActionExecutor",
            {"property": {"x": 0, "y": 0}, "unit_type": "Infantry"},
        ),
        ("end_turn", "EndTurnActionExecutor", {}),
        ("surrender", "SurrenderActionExecutor", {}),
    ],
)
@run_async_test
async def test_dispatch_uses_current_tracker_after_restore_and_commits_boundary(
    memory, tmp_path, monkeypatch, kind, executor_name, extra
):
    import aw2_lab.playable_runtime as module

    runtime, public, match_id, operator, bridge = await setup(memory, tmp_path)
    calls = []

    class Executor:
        def __init__(self, navigator, tracker):
            assert navigator.bridge is bridge
            self.tracker = tracker

        async def execute(self, request, observation):
            assert self.tracker is runtime.checkpoints.session.tracker
            calls.append(request.action.kind)
            bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(module, executor_name, Executor)
    try:
        start = await public.start(operator, match_id, start_request())
        started = await public.wait_for_command(operator, match_id, start.command_id, timeout=2)
        original_tracker = runtime.checkpoints.session.tracker
        restore = await runtime.checkpoints.restore(
            match_id, started.checkpoint_id, operator, request_id=uuid4(), expected_revision=1
        )
        restored = await public.wait_for_command(operator, match_id, restore.command_id, timeout=2)
        assert runtime.checkpoints.session.tracker is not original_tracker
        player = public.authenticate(token("p"))
        command = await public.submit(
            player,
            match_id,
            GameplayCommandRequest(
                request_id=uuid4(),
                expected_revision=restored.resulting_revision,
                action={"kind": kind, **extra},
            ),
        )
        result = await public.wait_for_command(player, match_id, command.command_id, timeout=2)
        assert result.status is CommandStatus.COMPLETED
        assert calls == [kind]
        assert runtime.store.current().command_result == result
        assert result.resulting_revision == restored.resulting_revision + 1
    finally:
        await public.controller.stop()


@run_async_test
async def test_rollback_replaces_shared_tracker_and_next_command_uses_it(
    memory, tmp_path, monkeypatch
):
    import aw2_lab.playable_runtime as module

    runtime, public, match_id, operator, bridge = await setup(memory, tmp_path)

    async def save_screenshot(path):
        path.write_bytes(b"synthetic failure screenshot")
        return path

    bridge.save_screenshot = save_screenshot

    class Executor:
        attempts = 0

        def __init__(self, navigator, tracker):
            self.tracker = tracker
            self.navigator = navigator

        async def execute(self, request, observation):
            Executor.attempts += 1
            bridge.frame += 1
            if Executor.attempts == 1:
                self.navigator._begin("choose_unload")
                self.navigator.inputs.append(
                    InputEvent("begin-unload", 1, 1, bridge.frame - 1, bridge.frame)
                )
                raise await self.navigator._fail(
                    "Timed out waiting for Drop cursor", await bridge.decoded()
                )
            assert self.tracker is runtime.checkpoints.session.tracker
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(module, "EndTurnActionExecutor", Executor)
    try:
        start = await public.start(operator, match_id, start_request())
        await public.wait_for_command(operator, match_id, start.command_id, timeout=2)
        player = public.authenticate(token("p"))
        for revision, expected in ((1, CommandStatus.ROLLED_BACK), (2, CommandStatus.COMPLETED)):
            command = await public.submit(
                player,
                match_id,
                GameplayCommandRequest(
                    request_id=uuid4(), expected_revision=revision, action={"kind": "end_turn"}
                ),
            )
            result = await public.wait_for_command(player, match_id, command.command_id, timeout=2)
            assert result.status is expected
            if expected is CommandStatus.ROLLED_BACK:
                assert result.error is not None
                assert (
                    result.error.details["navigation_message"]
                    == "Timed out waiting for Drop cursor"
                )
                context = json.loads(str(result.error.details["navigation_context"]))
                assert context["operation"] == "choose_unload"
                assert context["menu_family"] == "map_input"
                screenshot = Path(context["screenshot"])
                assert screenshot.parent == runtime.store.root / "navigation-failures"
                assert screenshot.read_bytes() == b"synthetic failure screenshot"
                assert context["input_sequence"][0]["name"] == "begin-unload"
                # The terminal receipt survives restart with its diagnostic context.
                entries = (await runtime.journal.read_entries()).entries
                assert entries[-1].error == result.error
        assert bridge.loads == 1
    finally:
        await public.controller.stop()


@run_async_test
async def test_finished_boundary_is_checkpointed_and_recovers_without_live_units(
    memory, tmp_path, monkeypatch
):
    from struct import pack_into

    import aw2_lab.playable_runtime as module
    from aw2_lab.match_checkpoint import CheckpointSession, MatchCheckpointService
    from aw2_lab.match_observation import IdentityStatus, MatchObservationTracker

    runtime, public, match_id, operator, bridge = await setup(memory, tmp_path)

    class Finish:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            pack_into("<I", memory[1], 0xD610, 0x0849D56C)
            bridge.frame += 1
            state = await bridge.decoded()
            return MutationOutcome(
                observation=self.tracker.commit_terminal_boundary(state),
                lifecycle=MatchLifecycle.FINISHED,
            )

    monkeypatch.setattr(module, "SurrenderActionExecutor", Finish)
    try:
        start = await public.start(operator, match_id, start_request())
        await public.wait_for_command(operator, match_id, start.command_id, timeout=2)
        command = await public.submit(
            public.authenticate(token("p")),
            match_id,
            GameplayCommandRequest(
                request_id=uuid4(), expected_revision=1, action={"kind": "surrender"}
            ),
        )
        result = await public.wait_for_command(operator, match_id, command.command_id, timeout=2)
        assert result.status is CommandStatus.COMPLETED
        assert (await public.state(operator, match_id)).summary.lifecycle is MatchLifecycle.FINISHED
        assert runtime.store.current().command_result == result
    finally:
        await public.controller.stop()
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    restarted = MatchController(
        authorization=auth, checkpoint_store=runtime.store, journal=runtime.journal
    )
    session = CheckpointSession(MatchObservationTracker(match_id), bridge.decoded)
    checkpoints = MatchCheckpointService(
        controller=restarted,
        store=runtime.store,
        bridge=bridge,
        session=session,
        runtime=runtime.identity,
        journal=runtime.journal,
    )
    await checkpoints.restore_startup_checkpoint(result.checkpoint_id, durable_revision_floor=2)
    state = await restarted.current_state(match_id)
    assert state.summary.lifecycle is MatchLifecycle.FINISHED
    assert state.observation.revision == 3
    assert state.observation.identity_status is IdentityStatus.UNAVAILABLE
    assert (
        state.observation.unit_identities == ()
        and state.observation.game_state.battle.value is None
    )


@run_async_test
async def test_interrupted_start_without_checkpoint_recovers_only_inspection_and_close(
    memory, tmp_path
):
    from types import SimpleNamespace

    from aw2_lab.api.app import _recover_checkpoint_on_startup
    from aw2_lab.command_journal import JournalEvent
    from aw2_lab.emulator import EmulatorSettings

    async def fail():
        raise RuntimeError("interrupted menu navigation")

    runtime, public, match_id, operator, _bridge = await setup(memory, tmp_path, boot=fail)
    receipt = await public.start(operator, match_id, start_request())
    await public.wait_for_command(operator, match_id, receipt.command_id, timeout=2)
    await public.controller.stop()
    entries = (await runtime.journal.read_entries()).entries
    runtime.journal.path.write_text(
        "".join(
            entry.model_dump_json() + "\n"
            for entry in entries
            if not (entry.command_id == receipt.command_id and entry.event is JournalEvent.TERMINAL)
        )
    )
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    restarted = MatchController(
        authorization=auth, journal=runtime.journal, checkpoint_store=runtime.store
    )
    assert (
        await _recover_checkpoint_on_startup(
            restarted,
            runtime.store,
            runtime.journal,
            SimpleNamespace(),
            EmulatorSettings(rom_path=tmp_path / "unused.gba"),
            memory[0].profile.sha256,
        )
        is None
    )
    await restarted.recover_authorized_setup()
    await restarted.start()
    try:
        recovered = AuthorizedMatchService(restarted)
        principal = recovered.authenticate(token("o"))
        state = await recovered.state(principal, match_id)
        assert (
            state.observation is None
            and state.summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED
        )
        command = await recovered.command_status(principal, match_id, receipt.command_id)
        assert command.status is CommandStatus.RECOVERY_REQUIRED
        close = await recovered.close(principal, match_id, uuid4())
        assert (
            await recovered.wait_for_command(principal, match_id, close.command_id, timeout=1)
        ).status is CommandStatus.COMPLETED
    finally:
        await restarted.stop()


def test_fixed_rule_selectors_reject_unverified_combinations():
    from dataclasses import replace

    from aw2_lab.cold_boot import ColdBootError, _FrontendState, _verify_rules
    from aw2_lab.lifecycle import LifecyclePhase

    state = _FrontendState(
        frame=0,
        phase=LifecyclePhase.VERSUS_SETUP,
        map_id=1,
        setup_subphase=2,
        setup=b"",
        selector_object=0,
        selector_table=0,
        yes_no_selection=0,
        fog_rule=1,
        weather_rule=1,
        income_rule=0,
        day_rule=26,
        capture_rule=0,
        powers_rule=0,
    )
    _verify_rules(state)
    for field, value in (
        ("fog_rule", 0),
        ("weather_rule", 0),
        ("income_rule", 1),
        ("day_rule", 0),
        ("capture_rule", 1),
        ("powers_rule", 1),
    ):
        with pytest.raises(ColdBootError):
            _verify_rules(replace(state, **{field: value}))


def test_first_turn_verification_checks_actual_roster_weather_fog_and_income(memory):
    from dataclasses import replace

    from test_state_validation import snapshot

    from aw2_lab.cold_boot import ColdBootError, _verify_playable_state
    from aw2_lab.state_decoder import decode_snapshot
    from aw2_lab.state_model import ObservedValue, ValueStatus, Weather

    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    players = tuple(
        replace(
            player,
            control_type=1,
            co_id=player.slot,
            team_id=player.slot - 1,
            funds=11000 if player.slot == 1 else 0,
        )
        for player in battle.players
    )
    battle = replace(
        battle,
        map=replace(battle.map, width=16, height=15),
        players=players,
        weather=ObservedValue(ValueStatus.AVAILABLE, Weather.CLEAR),
        fog_enabled=ObservedValue(ValueStatus.AVAILABLE, False),
        co_effects_enabled=ObservedValue(ValueStatus.AVAILABLE, True),
    )
    state = replace(state, battle=ObservedValue(ValueStatus.AVAILABLE, battle))
    _verify_playable_state(state, 1)
    for changed in (
        replace(battle, fog_enabled=ObservedValue(ValueStatus.AVAILABLE, True)),
        replace(battle, co_effects_enabled=ObservedValue(ValueStatus.AVAILABLE, False)),
        replace(battle, players=(replace(players[0], funds=1000), players[1])),
        replace(battle, players=(replace(players[0], control_type=2), players[1])),
        replace(battle, weather=ObservedValue(ValueStatus.AVAILABLE, Weather.RAIN)),
    ):
        with pytest.raises(ColdBootError):
            _verify_playable_state(
                replace(state, battle=ObservedValue(ValueStatus.AVAILABLE, changed)), 1
            )
