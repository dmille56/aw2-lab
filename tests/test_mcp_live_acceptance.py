"""Opt-in gameplay through actual MCP HTTP host sessions and the SDK."""

import asyncio
import base64
import hashlib
import json
import os
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from test_sdk_live_integration import coords, server, sha

from aw2_lab.match_contract import (
    CommandStatus,
    Coordinate,
    EndTurnAction,
    MoveCaptureAction,
    MoveWaitAction,
    PlayerSlot,
    PurchaseAction,
)
from aw2_lab.sdk import TERMINAL, AsyncAW2Client

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MCP_LIVE_TESTS") != "1",
    reason="set AW2_RUN_MCP_LIVE_TESTS=1 and AW2_ROM_PATH for MCP gameplay acceptance",
)


@asynccontextmanager
async def mcp_host(url: str, credential: SecretStr, *, message_handler=None):
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {credential.get_secret_value()}"}
        ) as http,
        streamable_http_client(url + "/mcp/", http_client=http) as (read, write, _),
        ClientSession(read, write, message_handler=message_handler) as session,
    ):
        await session.initialize()
        yield session


class LazyMCPHost:
    """Open a player session only after the SDK has accepted its invitation."""

    def __init__(self, stack: AsyncExitStack, url: str, credential: SecretStr):
        self.stack = stack
        self.url = url
        self.credential = credential
        self.session = None

    async def call_tool(self, name: str, arguments: dict):
        if self.session is None:
            self.session = await self.stack.enter_async_context(mcp_host(self.url, self.credential))
        return await self.session.call_tool(name, arguments)


@asynccontextmanager
async def clients(url: str, operator: SecretStr, players: tuple[SecretStr, SecretStr]):
    async with AsyncExitStack() as stack:
        result = {
            "admin": await stack.enter_async_context(AsyncAW2Client(url, credential=operator)),
            "red_sdk": await stack.enter_async_context(AsyncAW2Client(url, credential=players[0])),
            "blue_sdk": await stack.enter_async_context(AsyncAW2Client(url, credential=players[1])),
            "operator_mcp": await stack.enter_async_context(mcp_host(url, operator)),
            "red_mcp": LazyMCPHost(stack, url, players[0]),
            "blue_mcp": LazyMCPHost(stack, url, players[1]),
        }
        yield result


async def tool(host: ClientSession, name: str, arguments: dict):
    async with asyncio.timeout(75):
        response = await host.call_tool(name, arguments)
    assert not response.isError, response
    assert response.structuredContent is not None, response
    return response.structuredContent


async def state_revision(host: ClientSession, match_id):
    state = await tool(host, "get_state", {"match_id": str(match_id)})
    return state["summary"]["revision"]


async def mcp_action(host, match_id, name, arguments, *, request_id=None):
    request_id = request_id or uuid4()
    revision = await state_revision(host, match_id)
    receipt = await tool(
        host,
        name,
        {
            "match_id": str(match_id),
            "expected_revision": revision,
            "request_id": str(request_id),
            **arguments,
        },
    )
    command = None
    for _ in range(300):
        command = await tool(
            host,
            "get_command",
            {"match_id": str(match_id), "command_id": receipt["command_id"]},
        )
        if command["status"] in {status.value for status in TERMINAL}:
            break
        await asyncio.sleep(0.2)
    assert command is not None and command["status"] in {status.value for status in TERMINAL}, (
        "MCP command did not reach a terminal status within 60 seconds"
    )
    assert command["status"] == CommandStatus.COMPLETED.value, command
    return command, request_id


async def sdk_action(client, match_id, action):
    state = await client.state(match_id)
    receipt = await client.submit(match_id, state.summary.revision, action)
    done = await client.wait_for_command(match_id, receipt.command_id, timeout=60)
    assert done.status is CommandStatus.COMPLETED, done.error
    return done


def unit_identity(state, unit_type, army_slot):
    battle = state.observation.game_state.battle.value
    unit = next(
        (
            unit
            for unit in battle.units
            if unit.unit_type == unit_type and unit.army_slot == army_slot
        ),
        None,
    )
    assert unit is not None, [
        (candidate.unit_type, candidate.army_slot, candidate.x, candidate.y)
        for candidate in battle.units
    ]
    return next(
        identity.identity_id
        for identity in state.observation.unit_identities
        if identity.reference == unit.reference
    )


@pytest.mark.parametrize("mode", ["headless", "windowed"])
@pytest.mark.parametrize("red_protocol", ["sdk", "mcp"])
def test_live_mcp_hosts_play_shared_match(mode, red_protocol, tmp_path):
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check():
        operator = SecretStr(token_urlsafe(32))
        player_tokens = (SecretStr(token_urlsafe(32)), SecretStr(token_urlsafe(32)))
        token_file = tmp_path / "operator-token"
        token_file.write_text(operator.get_secret_value())
        token_file.chmod(0o600)
        evidence = {
            "mode": mode,
            "red_protocol": red_protocol,
            "blue_protocol": "mcp",
            "host_model": "deterministic test driver",
            "mcp_sdk_version": version("mcp"),
            "rom_sha256": sha(rom.read_bytes()),
            "commands": [],
            "boundaries": [],
        }
        match_id = None
        blue_purchase_id = uuid4()
        blue_purchase_command = None

        async with (
            server(tmp_path, mode, rom) as url,
            clients(url, operator, player_tokens) as connected,
        ):
            admin = connected["admin"]
            red = connected[f"red_{red_protocol}"]
            blue = connected["blue_mcp"]
            match = await admin.create_match()
            match_id = match.match_id
            for slot, _credential in zip(PlayerSlot, player_tokens, strict=True):
                invitation = SecretStr(token_urlsafe(32))
                await admin.invite(match_id, slot, invitation)
                player = connected["red_sdk" if slot is PlayerSlot.SLOT_1 else "blue_sdk"]
                await player.join(match_id, slot, invitation, slot.value)
            started = await admin.start(match_id, 0)
            result = await admin.wait_for_command(match_id, started.command_id, timeout=200)
            assert result.status is CommandStatus.COMPLETED, result.error
            assert result.checkpoint_id is not None
            start_checkpoint = await admin.inspect_checkpoint(match_id, result.checkpoint_id)
            evidence["emulator_build"] = start_checkpoint.compatibility.emulator_build
            evidence["emulator_mode"] = start_checkpoint.compatibility.emulator_mode

            initial = await connected["red_sdk"].state(match_id)
            assert initial.settled, initial.model_dump_json()

            if red_protocol == "sdk":
                await sdk_action(
                    red,
                    match_id,
                    PurchaseAction(property=Coordinate(x=3, y=6), unit_type="Infantry"),
                )
                await sdk_action(
                    red,
                    match_id,
                    PurchaseAction(property=Coordinate(x=1, y=6), unit_type="Tank"),
                )
                await sdk_action(red, match_id, EndTurnAction())
            else:
                await mcp_action(
                    red,
                    match_id,
                    "purchase",
                    {"property": {"x": 3, "y": 6}, "unit_type": "Infantry"},
                )
                await mcp_action(
                    red,
                    match_id,
                    "purchase",
                    {"property": {"x": 1, "y": 6}, "unit_type": "Tank"},
                )
                await mcp_action(red, match_id, "end_turn", {})

            purchase, blue_purchase_id = await mcp_action(
                blue,
                match_id,
                "purchase",
                {"property": {"x": 12, "y": 6}, "unit_type": "Tank"},
                request_id=blue_purchase_id,
            )
            blue_purchase_command = purchase["command_id"]
            # Durable command receipts make a lost-response retry idempotent.
            retry = await tool(
                blue,
                "purchase",
                {
                    "match_id": str(match_id),
                    "expected_revision": purchase["accepted_revision"],
                    "request_id": str(blue_purchase_id),
                    "property": {"x": 12, "y": 6},
                    "unit_type": "Tank",
                },
            )
            assert retry["command_id"] == blue_purchase_command
            await mcp_action(blue, match_id, "end_turn", {})

            after_purchase = await connected["admin"].state(match_id)
            infantry = unit_identity(after_purchase, 1, 1)
            red_tank = unit_identity(after_purchase, 5, 1)
            blue_tank = unit_identity(after_purchase, 5, 2)

            async def red_do(name, args, sdk_action_value=None):
                if red_protocol == "mcp":
                    result, _ = await mcp_action(red, match_id, name, args)
                else:
                    result = await sdk_action(red, match_id, sdk_action_value)
                evidence["commands"].append({"player": "red", "tool": name})
                return result

            await red_do(
                "move_wait",
                {"unit_id": infantry, "path": [{"x": 3, "y": 5}, {"x": 4, "y": 5}]},
                MoveWaitAction(unit_id=infantry, path=coords([(3, 5), (4, 5)])),
            )
            await red_do(
                "move_wait",
                {
                    "unit_id": red_tank,
                    "path": [
                        {"x": 1, "y": 7},
                        {"x": 1, "y": 8},
                        {"x": 1, "y": 9},
                        {"x": 2, "y": 9},
                        {"x": 3, "y": 9},
                        {"x": 4, "y": 9},
                    ],
                },
                MoveWaitAction(
                    unit_id=red_tank,
                    path=coords([(1, 7), (1, 8), (1, 9), (2, 9), (3, 9), (4, 9)]),
                ),
            )
            await red_do("end_turn", {}, EndTurnAction())
            await mcp_action(
                blue,
                match_id,
                "move_wait",
                {
                    "unit_id": blue_tank,
                    "path": [
                        {"x": 12, "y": 7},
                        {"x": 12, "y": 8},
                        {"x": 12, "y": 9},
                        {"x": 11, "y": 9},
                        {"x": 10, "y": 9},
                    ],
                },
            )
            await mcp_action(blue, match_id, "end_turn", {})
            await red_do(
                "move_capture",
                {"unit_id": infantry, "path": [{"x": 5, "y": 5}, {"x": 5, "y": 4}]},
                MoveCaptureAction(unit_id=infantry, path=coords([(5, 5), (5, 4)])),
            )
            await red_do("end_turn", {}, EndTurnAction())
            await mcp_action(blue, match_id, "surrender", {})

            midgame = await connected["admin"].state(match_id)
            assert midgame.observation.game_state.battle.value is None
            assert midgame.summary.lifecycle.value == "finished"
            if red_protocol == "mcp":
                assert await state_revision(red, match_id) == midgame.summary.revision
            mcp_image = await blue.call_tool(
                "get_screenshot", {"match_id": str(match_id), "revision": midgame.summary.revision}
            )
            assert not mcp_image.isError, mcp_image
            screenshot = mcp_image.structuredContent
            assert screenshot is not None
            assert screenshot["revision"] == midgame.summary.revision
            assert any(block.type == "image" for block in mcp_image.content)
            evidence["victory_screenshot"] = {
                "revision": screenshot["revision"],
                "frame": screenshot["frame"],
                "png_sha256": hashlib.sha256(
                    base64.b64decode(
                        next(block.data for block in mcp_image.content if block.type == "image")
                    )
                ).hexdigest(),
            }
            evidence["passed"] = True
            (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_mcp_checkpoint_restart_notifications_and_wait(mode, tmp_path):
    """Exercise MCP checkpoint transfers, restart recovery, notifications, and waits live."""
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check():
        operator = SecretStr(token_urlsafe(32))
        players = (SecretStr(token_urlsafe(32)), SecretStr(token_urlsafe(32)))
        token_file = tmp_path / "operator-token"
        token_file.write_text(operator.get_secret_value())
        token_file.chmod(0o600)
        evidence = {
            "mode": mode,
            "host_model": "deterministic test driver",
            "mcp_sdk_version": version("mcp"),
            "rom_sha256": sha(rom.read_bytes()),
            "events": [],
        }
        match_id = None
        saved_state = None
        saved_checkpoint = None
        purchase_id = uuid4()
        purchase_command_id = None

        async with (
            server(tmp_path, mode, rom) as url,
            clients(url, operator, players) as connected,
        ):
            admin = connected["admin"]
            match = await admin.create_match()
            match_id = match.match_id
            for slot, credential in zip(PlayerSlot, players, strict=True):
                invitation = SecretStr(token_urlsafe(32))
                await admin.invite(match_id, slot, invitation)
                player = connected["red_sdk" if slot is PlayerSlot.SLOT_1 else "blue_sdk"]
                await player.join(match_id, slot, invitation, slot.value)
            started = await admin.start(match_id, 0)
            start_result = await admin.wait_for_command(match_id, started.command_id, timeout=200)
            assert start_result.status is CommandStatus.COMPLETED, start_result.error

            red = connected["red_mcp"]
            before = await connected["red_sdk"].state(match_id)
            evidence["emulator_build"] = (
                await admin.inspect_checkpoint(match_id, start_result.checkpoint_id)
            ).compatibility.emulator_build

            state_uri = f"aw2://v1/matches/{match_id}/state"
            # Create/export/import via MCP, then restore after a distinct committed action.
            create = await tool(
                red,
                "create_checkpoint",
                {
                    "match_id": str(match_id),
                    "expected_revision": before.summary.revision,
                    "request_id": str(uuid4()),
                },
            )
            command_wait = await tool(
                red,
                "wait_for_command",
                {
                    "match_id": str(match_id),
                    "command_id": create["command_id"],
                    "timeout_seconds": 60,
                },
            )
            assert not command_wait["timed_out"]
            assert command_wait["command"]["status"] == "completed"
            saved_checkpoint = command_wait["command"]["checkpoint_id"]
            saved_state = await connected["red_sdk"].state(match_id)
            assert saved_state.settled

            exported = await tool(
                connected["operator_mcp"],
                "export_checkpoint",
                {"match_id": str(match_id), "checkpoint_id": saved_checkpoint},
            )
            archive = base64.b64decode(exported["archive_base64"], validate=True)
            assert hashlib.sha256(archive).hexdigest() == exported["sha256"]
            imported = await tool(
                connected["operator_mcp"],
                "import_checkpoint",
                {
                    "match_id": str(match_id),
                    "request_id": str(uuid4()),
                    "archive_base64": exported["archive_base64"],
                },
            )
            assert imported["checkpoint_id"] == saved_checkpoint

            receipt = await tool(
                red,
                "purchase",
                {
                    "match_id": str(match_id),
                    "expected_revision": saved_state.summary.revision,
                    "request_id": str(purchase_id),
                    "property": {"x": 3, "y": 6},
                    "unit_type": "Infantry",
                },
            )
            purchase_command_id = receipt["command_id"]
            purchase_status = None
            for _ in range(300):
                purchase_status = await tool(
                    red,
                    "get_command",
                    {"match_id": str(match_id), "command_id": purchase_command_id},
                )
                if purchase_status["status"] in {status.value for status in TERMINAL}:
                    break
                await asyncio.sleep(0.2)
            assert purchase_status is not None
            assert purchase_status["status"] == CommandStatus.COMPLETED.value

            changed_state = await connected["red_sdk"].state(match_id)
            assert changed_state.summary.revision > saved_state.summary.revision
            notifications = asyncio.Queue()

            async def handle_message(message):
                notifications.put_nowait(message.root)

            state_uri = f"aw2://v1/matches/{match_id}/state"
            async with mcp_host(url, operator, message_handler=handle_message) as listener:
                await listener.send_request(
                    types.SubscribeRequest(params=types.SubscribeRequestParams(uri=state_uri)),
                    types.EmptyResult,
                )
                evidence["events"].append(str(await asyncio.wait_for(notifications.get(), 10)))
                restore = await tool(
                    connected["operator_mcp"],
                    "restore_checkpoint",
                    {
                        "match_id": str(match_id),
                        "checkpoint_id": saved_checkpoint,
                        "expected_revision": changed_state.summary.revision,
                        "request_id": str(uuid4()),
                    },
                )
                restored_cmd = None
                for _ in range(300):
                    restored_cmd = await tool(
                        connected["operator_mcp"],
                        "get_command",
                        {
                            "match_id": str(match_id),
                            "command_id": restore["command_id"],
                        },
                    )
                    if restored_cmd["status"] in {status.value for status in TERMINAL}:
                        break
                    await asyncio.sleep(0.2)
                assert restored_cmd is not None
                assert restored_cmd["status"] == "completed"
                evidence["events"].append(str(await asyncio.wait_for(notifications.get(), 10)))
                resource = await listener.read_resource(state_uri)
                assert resource.contents
                assert (
                    json.loads(resource.contents[0].text)["summary"]["revision"]
                    == (restored_cmd["resulting_revision"])
                )
            restored = await connected["red_sdk"].state(match_id)
            assert restored.observation.game_state == saved_state.observation.game_state
            assert restored.observation.unit_identities == saved_state.observation.unit_identities
            assert restored.summary.revision > changed_state.summary.revision
            assert await connected["admin"].state(match_id) == restored
            evidence["restored_revision"] = restored.summary.revision

        # A clean process shutdown/restart must restore the active checkpoint.
        async with server(tmp_path, mode, rom) as url:
            async with (
                AsyncAW2Client(url, credential=operator) as admin,
                mcp_host(url, players[0]) as red,
            ):
                resumed = await admin.state(match_id)
                assert resumed.observation.game_state == saved_state.observation.game_state
                assert (
                    resumed.observation.unit_identities == saved_state.observation.unit_identities
                )
                assert resumed.summary.revision >= evidence["restored_revision"]
                # Replaying the accepted purchase after restart must return its durable receipt.
                retry = await tool(
                    red,
                    "purchase",
                    {
                        "match_id": str(match_id),
                        "expected_revision": saved_state.summary.revision,
                        "request_id": str(purchase_id),
                        "property": {"x": 3, "y": 6},
                        "unit_type": "Infantry",
                    },
                )
                assert retry["command_id"] == purchase_command_id
                assert await admin.state(match_id) == resumed
                evidence["restart_revision"] = resumed.summary.revision

                # Reconnect as a new host session, resubscribe, and resynchronize by reading.
                reconnect_notices = asyncio.Queue()

                async def handle_reconnect(message):
                    reconnect_notices.put_nowait(message.root)

                async with mcp_host(url, operator, message_handler=handle_reconnect) as host:
                    await host.send_request(
                        types.SubscribeRequest(params=types.SubscribeRequestParams(uri=state_uri)),
                        types.EmptyResult,
                    )
                    await asyncio.wait_for(reconnect_notices.get(), timeout=10)
                    snapshot = await host.read_resource(state_uri)
                    assert snapshot.contents
                    evidence["reconnect_resource"] = snapshot.contents[0].text

                    # Player waits are bounded and settle from the shared publisher.
                    wait_result = await tool(
                        red,
                        "wait_for_turn",
                        {
                            "match_id": str(match_id),
                            "player_slot": "slot_1",
                            "after_revision": resumed.summary.revision,
                            "timeout_seconds": 2,
                        },
                    )
                    assert wait_result["timed_out"]
                    assert wait_result["reason"] == "timed_out"
                    evidence["bounded_wait"] = wait_result["reason"]
                evidence["passed"] = True
            (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(check())
