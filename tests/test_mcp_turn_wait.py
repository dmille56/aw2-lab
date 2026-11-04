"""Bounded turn waits through mounted MCP, real SDK reads, and shared events."""

import asyncio
from struct import pack_into
from uuid import uuid4

from test_authorization import token
from test_http_api import application
from test_http_gameplay_checkpoints import setup
from test_match_controller import run_async_test
from test_mcp_authorization import headers, result, rpc
from test_mcp_tools import mounted, payload
from test_playable_runtime import setup as runtime_setup
from test_state_validation import memory as memory  # noqa: PLC0414

import aw2_lab.playable_runtime as runtime_module
from aw2_lab.api_contract import GameplayCommandRequest, StartMatchRequest
from aw2_lab.match_contract import CommandStatus, MatchLifecycle, PlayerSlot
from aw2_lab.match_controller import MutationOutcome


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


def args(match_id, *, slot="slot_1", after=0, timeout=1):
    return {
        "match_id": str(match_id),
        "player_slot": slot,
        "after_revision": after,
        "timeout_seconds": timeout,
    }


@run_async_test
async def test_turn_wait_ready_timeout_roles_versions_and_close(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, monkeypatch)
    before = await public.state(operator, match_id)
    try:
        async with mounted(app, monkeypatch) as (call, _, _):
            ready = payload(await call("wait_for_turn", args(match_id)))
            assert ready["reason"] == "turn_ready" and not ready["timed_out"]
            assert ready["state"] == before.model_dump(mode="json")
            timed = payload(await call("wait_for_turn", args(match_id, after=1, timeout=0.05)))
            assert timed["timed_out"] and timed["reason"] == "timed_out"
            assert timed["state"] == before.model_dump(mode="json")
            operator_wait = payload(
                await call("wait_for_turn", args(match_id, slot="slot_2", timeout=0.05), letter="o")
            )
            assert operator_wait["timed_out"]
            for changes, code in (
                ({"player_slot": "slot_2"}, "permission_denied"),
                ({"match_id": str(uuid4())}, "permission_denied"),
                ({"timeout_seconds": 61}, "invalid_request"),
                ({"timeout_seconds": 0}, "invalid_request"),
                ({"after_revision": -1}, "invalid_request"),
                ({"contract_version": 2}, "invalid_request"),
            ):
                response = await call("wait_for_turn", {**args(match_id), **changes})
                assert (
                    response["isError"] and response["structuredContent"]["error"]["code"] == code
                )
            assert await public.state(operator, match_id) == before
            assert bridge.frame == before.observation.game_state.frame
            receipt = await public.close(operator, match_id, uuid4())
            await runtime.controller.wait_for_command(match_id, receipt.command_id, timeout=2)
            closed = payload(await call("wait_for_turn", args(match_id, after=999)))
            assert closed["reason"] == "closed" and not closed["timed_out"]
            assert not runtime.controller.events._channels[match_id].subscribers
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_turn_change_wakes_waiter_and_does_not_hold_queue(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, _operator, bridge = await setup(memory, tmp_path, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    block_read = False

    def controlled_client(base):
        class Controlled(base):
            async def state(self, identifier):
                nonlocal block_read
                state = await super().state(identifier)
                if block_read:
                    block_read = False
                    entered.set()
                    await release.wait()
                return state

        return Controlled

    class Executor:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            bridge.frame += 1
            pack_into("<H", memory[2], 0x33EC, 2)
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(runtime_module, "EndTurnActionExecutor", Executor)
    try:
        async with mounted(app, monkeypatch, client_type=controlled_client) as (call, _, _):
            payload(await call("get_state", {"match_id": str(match_id)}, letter="q"))
            runtime.controller.events._subscriber_count = 1
            block_read = True
            wait = asyncio.create_task(
                call("wait_for_turn", args(match_id, slot="slot_2", after=1), letter="q")
            )
            await asyncio.wait_for(entered.wait(), 2)
            receipt = await public.submit(
                public.authenticate(token("p")),
                match_id,
                GameplayCommandRequest(
                    request_id=uuid4(), expected_revision=1, action={"kind": "end_turn"}
                ),
            )
            command = await runtime.controller.wait_for_command(
                match_id, receipt.command_id, timeout=2
            )
            assert command.status is CommandStatus.COMPLETED
            # Updates raced the stale HTTP read and overflowed its bounded event buffer.
            assert not runtime.controller.events._channels[match_id].subscribers
            release.set()
            result = payload(await wait)
            assert result["reason"] == "turn_ready" and result["state"]["summary"]["revision"] == 2
            assert bridge.frame == 124
            assert not runtime.controller.events._channels[match_id].subscribers
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_setup_waits_for_start_and_cancellation_cleans_up(memory, tmp_path, monkeypatch):
    runtime, public, match_id, operator, bridge = await runtime_setup(memory, tmp_path)
    app = application(runtime.controller, tmp_path, monkeypatch)
    try:
        async with mounted(app, monkeypatch) as (call, _, http):
            payload(await call("get_state", {"match_id": str(match_id)}))
            waiter = asyncio.create_task(call("wait_for_turn", args(match_id)))
            await eventually(
                lambda: bool(runtime.controller.events._channels[match_id].subscribers)
            )
            assert not waiter.done() and not hasattr(bridge, "resets")
            receipt = await public.start(
                operator, match_id, StartMatchRequest(request_id=uuid4(), expected_revision=0)
            )
            await runtime.controller.wait_for_command(match_id, receipt.command_id, timeout=2)
            assert payload(await waiter)["reason"] == "turn_ready"
            initialized = await http.post(
                "/mcp/",
                headers=headers("p"),
                json=rpc(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "cancel-test", "version": "1"},
                    },
                ),
            )
            auth = headers("p", initialized.headers["mcp-session-id"])
            await http.post(
                "/mcp/",
                headers=auth,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            waiter = asyncio.create_task(
                http.post(
                    "/mcp/",
                    headers=auth,
                    json=rpc(
                        "tools/call",
                        {
                            "name": "wait_for_turn",
                            "arguments": args(match_id, after=1, timeout=60),
                        },
                        identifier=100,
                    ),
                )
            )
            await eventually(
                lambda: bool(runtime.controller.events._channels[match_id].subscribers)
            )
            await http.post(
                "/mcp/",
                headers=auth,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 100},
                },
            )
            assert "error" in result(await asyncio.wait_for(waiter, 2))
            await eventually(lambda: not runtime.controller.events._channels[match_id].subscribers)
            assert bridge.frame == 123
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_wait_capacity_and_revocation_release_idle_waiters(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, monkeypatch)
    try:
        async with mounted(app, monkeypatch) as (call, _, _):
            payload(await call("get_state", {"match_id": str(match_id)}))
            waiters = [
                asyncio.create_task(call("wait_for_turn", args(match_id, after=1, timeout=60)))
                for _ in range(4)
            ]
            await eventually(
                lambda: len(runtime.controller.events._channels[match_id].subscribers) == 4
            )
            excess = await call("wait_for_turn", args(match_id, after=1))
            assert excess["structuredContent"]["error"]["code"] == "capacity_exceeded"
            await public.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
            results = await asyncio.wait_for(asyncio.gather(*waiters, return_exceptions=True), 2)
            for response in results:
                assert isinstance(response, Exception) or response.get("isError")
            await eventually(lambda: not runtime.controller.events._channels[match_id].subscribers)
            assert bridge.frame == 123
            assert (
                await public.state(operator, match_id)
            ).summary.lifecycle is MatchLifecycle.PLAYABLE
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_final_read_terminal_states_and_full_deadline(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, operator, _bridge = await setup(memory, tmp_path, monkeypatch)
    initial = await public.state(operator, match_id)
    lifecycle = MatchLifecycle.FINISHED
    read_count = 0
    hang_final = False

    def controlled_client(base):
        class Controlled(base):
            async def state(self, identifier):
                nonlocal read_count
                read_count += 1
                if read_count == 1 or hang_final:
                    await asyncio.sleep(1)
                return initial.model_copy(
                    update={"summary": initial.summary.model_copy(update={"lifecycle": lifecycle})}
                )

        return Controlled

    try:
        async with mounted(app, monkeypatch, client_type=controlled_client) as (call, _, _):
            for lifecycle in (
                MatchLifecycle.FINISHED,
                MatchLifecycle.CLOSED,
                MatchLifecycle.RECOVERY_REQUIRED,
            ):
                read_count = 0
                response = payload(
                    await call("wait_for_turn", args(match_id, after=999, timeout=0.1))
                )
                assert response["reason"] == lifecycle.value and not response["timed_out"]
                assert response["state"]["summary"]["revision"] == 1
                assert read_count == 2
            read_count = 0
            hang_final = True
            response = await call("wait_for_turn", args(match_id, after=1, timeout=0.1))
            assert (
                response["isError"] and response["structuredContent"]["error"]["code"] == "timeout"
            )
            assert not runtime.controller.events._channels[match_id].subscribers
    finally:
        await runtime.controller.stop()
