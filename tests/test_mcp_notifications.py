"""Authorized resource invalidations share controller events and session lifetimes."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import anyio
import pytest
from mcp import McpError
from pydantic import AnyUrl
from test_authorization import token
from test_http_gameplay_checkpoints import setup
from test_match_controller import run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab.authorization import AuthorizationError
from aw2_lab.match_contract import CommandResult, CommandStatus
from aw2_lab.mcp_auth import MCPCaller
from aw2_lab.mcp_notifications import MCPResourceNotifications


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@run_async_test
async def test_notifications_filter_bound_and_cleanup(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, monkeypatch)
    adapter = app.state.mcp_runtime
    notifications = MCPResourceNotifications(adapter)
    caller = MCPCaller(public.authorization, public.authenticate(token("p")), token("p"))
    delivered = []

    async def send(uri):
        delivered.append(str(uri))

    state_uri = AnyUrl(f"aw2://v1/matches/{match_id}/state")
    try:
        async with adapter.run(), anyio.create_task_group() as tasks:
            # Session objects are identity-hashable in the SDK.
            class Session:
                _task_group = tasks
                send_resource_updated = staticmethod(send)

            session = Session()
            await notifications.subscribe(caller, session, state_uri)
            await eventually(lambda: len(delivered) == 1)
            await notifications.subscribe(caller, session, state_uri)
            assert len(notifications.active) == 1
            state = await public.state(operator, match_id)
            runtime.controller.events.state_changed(
                state.model_copy(
                    update={
                        "summary": state.summary.model_copy(
                            update={"created_at": datetime.now(UTC)}
                        )
                    }
                )
            )
            await eventually(lambda: len(delivered) == 2)
            assert bridge.frame == state.observation.game_state.frame
            with pytest.raises(AuthorizationError):
                await notifications.subscribe(
                    caller, session, AnyUrl(f"aw2://v1/matches/{uuid4()}/state")
                )
            with pytest.raises(McpError):
                await notifications.subscribe(caller, session, AnyUrl("aw2://v1/unsupported"))
            notifications.unsubscribe(caller, session, state_uri)
            await eventually(lambda: not notifications.active)
            await eventually(lambda: not runtime.controller.events._channels[match_id].subscribers)
            command = CommandResult(
                command_id=uuid4(),
                request_id=uuid4(),
                match_id=match_id,
                status=CommandStatus.COMPLETED,
                accepted_revision=1,
                resulting_revision=1,
            )

            async def command_status(*args):
                return command

            monkeypatch.setattr(public.controller, "command_status", command_status)
            command_uri = AnyUrl(f"aw2://v1/matches/{match_id}/commands/{command.command_id}")
            await notifications.subscribe(caller, session, command_uri)
            await eventually(lambda: len(delivered) == 3)
            runtime.controller.events.command_changed(
                command.model_copy(update={"command_id": uuid4()})
            )
            runtime.controller.events.command_changed(command)
            await eventually(lambda: len(delivered) == 4)
            assert delivered[-1] == str(command_uri)
            # Revocation wakes idle subscribers without requiring another match update.
            from aw2_lab.match_contract import PlayerSlot

            await public.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
            await eventually(lambda: not notifications.active)
            await eventually(lambda: not runtime.controller.events._channels[match_id].subscribers)
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_mounted_subscription_protocol_and_session_delete(memory, tmp_path, monkeypatch):
    from mcp.server.session import ServerSession
    from test_mcp_authorization import headers, result, rpc
    from test_mcp_tools import mounted

    app, runtime, _public, match_id, _operator, _ = await setup(memory, tmp_path, monkeypatch)
    delivered = []
    original = ServerSession.send_resource_updated

    async def send(session, uri):
        await original(session, uri)
        delivered.append(str(uri))

    monkeypatch.setattr(ServerSession, "send_resource_updated", send)
    try:
        async with mounted(app, monkeypatch) as (_, _, http):
            response = await http.post(
                "/mcp/",
                headers=headers("p"),
                json=rpc(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "subscription-test", "version": "1"},
                    },
                ),
            )
            assert result(response)["result"]["capabilities"]["resources"]["subscribe"] is True
            session = response.headers["mcp-session-id"]
            auth = headers("p", session)
            await http.post(
                "/mcp/",
                headers=auth,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            uri = f"aw2://v1/matches/{match_id}/state"
            subscribed = await http.post(
                "/mcp/", headers=auth, json=rpc("resources/subscribe", {"uri": uri}, identifier=2)
            )
            assert result(subscribed)["result"] == {}
            await eventually(lambda: delivered == [uri])
            denied = await http.post(
                "/mcp/",
                headers=auth,
                json=rpc(
                    "resources/subscribe",
                    {"uri": f"aw2://v1/matches/{uuid4()}/state"},
                    identifier=3,
                ),
            )
            assert "error" in result(denied)
            assert (await http.delete("/mcp/", headers=auth)).status_code == 200
            await eventually(lambda: not runtime.controller.events._channels[match_id].subscribers)
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_subscription_capacity_and_session_cleanup(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, operator, _ = await setup(memory, tmp_path, monkeypatch)
    notifications = MCPResourceNotifications(app.state.mcp_runtime)
    caller = MCPCaller(public.authorization, operator, token("o"))
    command = CommandResult(
        command_id=uuid4(),
        request_id=uuid4(),
        match_id=match_id,
        status=CommandStatus.COMPLETED,
        accepted_revision=1,
        resulting_revision=1,
    )

    async def command_status(*args):
        return command

    monkeypatch.setattr(public.controller, "command_status", command_status)
    try:
        async with app.state.mcp_runtime.run():
            async with anyio.create_task_group() as tasks:

                class Session:
                    _task_group = tasks

                    async def send_resource_updated(self, uri):
                        pass

                session = Session()
                for _ in range(16):
                    await notifications.subscribe(
                        caller, session, AnyUrl(f"aw2://v1/matches/{match_id}/commands/{uuid4()}")
                    )
                with pytest.raises(McpError, match="capacity"):
                    await notifications.subscribe(
                        caller, session, AnyUrl(f"aw2://v1/matches/{match_id}/state")
                    )
                assert len(notifications.active) == 16
                tasks.cancel_scope.cancel()
            assert not notifications.active
            assert not runtime.controller.events._channels[match_id].subscribers
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_overflow_invalidates_and_resubscribes(memory, tmp_path, monkeypatch):
    from datetime import timedelta

    app, runtime, public, match_id, operator, _ = await setup(memory, tmp_path, monkeypatch)
    notifications = MCPResourceNotifications(app.state.mcp_runtime)
    caller = MCPCaller(public.authorization, operator, token("o"))
    entered, release = anyio.Event(), anyio.Event()
    delivered = []

    async def send(uri):
        entered.set()
        await release.wait()
        delivered.append(str(uri))

    runtime.controller.events._subscriber_count = 1
    uri = AnyUrl(f"aw2://v1/matches/{match_id}/state")
    try:
        async with app.state.mcp_runtime.run(), anyio.create_task_group() as tasks:

            class Session:
                _task_group = tasks
                send_resource_updated = staticmethod(send)

            session = Session()
            await notifications.subscribe(caller, session, uri)
            await entered.wait()
            state = await public.state(operator, match_id)
            for index in range(2):
                runtime.controller.events.state_changed(
                    state.model_copy(
                        update={
                            "summary": state.summary.model_copy(
                                update={
                                    "created_at": state.summary.created_at
                                    + timedelta(seconds=index + 1)
                                }
                            )
                        }
                    )
                )
            assert not runtime.controller.events._channels[match_id].subscribers
            release.set()
            await eventually(lambda: len(delivered) >= 3)
            assert len(notifications.active) == 1
            assert len(runtime.controller.events._channels[match_id].subscribers) == 1
            notifications.unsubscribe(caller, session, uri)
    finally:
        await runtime.controller.stop()
