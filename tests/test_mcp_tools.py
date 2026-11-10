"""Mounted MCP tools through the real SDK, HTTP facade, queue, and checkpoint store."""

import asyncio
import base64
import hashlib
from contextlib import asynccontextmanager
from itertools import count
from uuid import UUID, uuid4

import httpx
import pytest
from test_authorization import token
from test_http_api import application
from test_http_gameplay_checkpoints import setup
from test_match_controller import run_async_test
from test_mcp_authorization import headers, result, rpc
from test_state_validation import memory as memory  # noqa: PLC0414

import aw2_lab.mcp_runtime as adapter_module
import aw2_lab.playable_runtime as runtime_module
from aw2_lab.authorization import AuthorizationService
from aw2_lab.match_contract import CommandResult, CommandStatus, MatchLifecycle
from aw2_lab.match_controller import MatchController, MutationOutcome
from aw2_lab.sdk import AsyncAW2Client, TransportError, WaitTimeout


@asynccontextmanager
async def mounted(app, monkeypatch, *, client_type=None):
    clients = []

    class LocalSDK(AsyncAW2Client):
        def __init__(self, base_url, *, credential):
            super().__init__(
                base_url, credential=credential, transport=httpx.ASGITransport(app=app), retries=0
            )
            clients.append(self)

    sdk_type = client_type(LocalSDK) if client_type else LocalSDK
    monkeypatch.setattr(adapter_module, "AsyncAW2Client", sdk_type)
    sessions = {}
    identifiers = count(1)
    async with (
        app.state.mcp_runtime.run(),
        app.state.mcp_server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as http,
    ):

        async def call(name, arguments=None, *, letter="p"):
            if letter not in sessions:
                response = await http.post(
                    "/mcp/",
                    headers=headers(letter),
                    json=rpc(
                        "initialize",
                        {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                        identifier=next(identifiers),
                    ),
                )
                assert result(response)["result"]
                sessions[letter] = response.headers["mcp-session-id"]
                await http.post(
                    "/mcp/",
                    headers=headers(letter, sessions[letter]),
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
            method = "resources/read" if name == "_resource_read" else "tools/call"
            params = arguments or {}
            if method == "tools/call":
                params = {"name": name, "arguments": params}
            response = result(
                await http.post(
                    "/mcp/",
                    headers=headers(letter, sessions[letter]),
                    json=rpc(method, params, identifier=next(identifiers)),
                )
            )
            return response.get("result", response)

        yield call, clients, http
    assert all(client._http.is_closed for client in clients)


def payload(response):
    assert not response.get("isError"), response
    return response["structuredContent"]


@pytest.mark.parametrize(
    "kind,executor,extra",
    [
        ("move_wait", "MoveWaitActionExecutor", {"unit_id": "1", "path": []}),
        (
            "move_attack",
            "MoveAttackActionExecutor",
            {"unit_id": "1", "path": [], "target": {"x": 1, "y": 1}},
        ),
        ("attack", "MoveAttackActionExecutor", {"unit_id": "1", "target": {"x": 1, "y": 1}}),
        ("move_capture", "MoveCaptureActionExecutor", {"unit_id": "1", "path": []}),
        ("join", "JoinActionExecutor", {"unit_id": "1", "path": [{"x": 1, "y": 0}]}),
        ("supply", "SupplyActionExecutor", {"unit_id": "1", "path": []}),
        ("dive", "DiveActionExecutor", {"unit_id": "1", "path": []}),
        ("rise", "RiseActionExecutor", {"unit_id": "1", "path": []}),
        (
            "unload",
            "UnloadActionExecutor",
            {
                "transport_id": "3",
                "path": [],
                "drops": [{"unit_id": "4", "destination": {"x": 1, "y": 0}}],
            },
        ),
        (
            "purchase",
            "PurchaseActionExecutor",
            {"property": {"x": 1, "y": 1}, "unit_type": "Infantry"},
        ),
        ("end_turn", "EndTurnActionExecutor", {}),
        ("surrender", "SurrenderActionExecutor", {}),
    ],
)
@run_async_test
async def test_gameplay_receipts_retries_conflicts_and_permissions(
    memory, tmp_path, monkeypatch, kind, executor, extra
):
    app, runtime, _, match_id, _, bridge = await setup(memory, tmp_path, monkeypatch)
    executed = []

    class Executor:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            executed.append(request.action.model_dump(mode="json"))
            bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(runtime_module, executor, Executor)
    try:
        async with mounted(app, monkeypatch) as (call, _clients, http):
            args = {
                "match_id": str(match_id),
                "expected_revision": 1,
                "request_id": str(uuid4()),
                **extra,
            }
            denied = await call(kind, args, letter="o")
            assert denied["structuredContent"]["error"]["code"] == "permission_denied"
            receipt = payload(await call(kind, args))
            await runtime.controller.wait_for_command(
                match_id, UUID(receipt["command_id"]), timeout=2
            )
            assert payload(await call(kind, args))["command_id"] == receipt["command_id"]
            complete = payload(
                await call(
                    "wait_for_command",
                    {"match_id": str(match_id), "command_id": receipt["command_id"]},
                )
            )
            assert not complete["timed_out"] and complete["command"]["status"] == "completed"
            expected = {"contract_version": 1, "kind": kind, **extra}
            if "path" in expected:
                expected["path"] = [{"contract_version": 1, **point} for point in expected["path"]]
            for field in ("target", "property"):
                if field in expected:
                    expected[field] = {"contract_version": 1, **expected[field]}
            if "drops" in expected:
                expected["drops"] = [
                    {
                        "contract_version": 1,
                        **drop,
                        "destination": {"contract_version": 1, **drop["destination"]},
                    }
                    for drop in expected["drops"]
                ]
            assert executed == [expected]
            conflict = await call(kind, {**args, "expected_revision": 2})
            assert conflict["structuredContent"]["error"]["code"] == "request_id_conflict"
            direct = (
                await http.get(
                    f"/v1/matches/{match_id}/commands/{receipt['command_id']}", headers=headers()
                )
            ).json()
            assert direct == payload(
                await call(
                    "get_command", {"match_id": str(match_id), "command_id": receipt["command_id"]}
                )
            )
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_checkpoint_archive_restore_and_revocation(memory, tmp_path, monkeypatch):
    app, runtime, _public, match_id, _operator, bridge = await setup(memory, tmp_path, monkeypatch)
    try:
        async with mounted(app, monkeypatch) as (call, _, http):
            common = {"match_id": str(match_id)}
            receipt = payload(
                await call(
                    "create_checkpoint",
                    {**common, "expected_revision": 1, "request_id": str(uuid4())},
                    letter="q",
                )
            )
            done = await runtime.controller.wait_for_command(
                match_id, UUID(receipt["command_id"]), timeout=2
            )
            checkpoint = {**common, "checkpoint_id": str(done.checkpoint_id)}
            assert payload(await call("list_checkpoints", common))["checkpoints"]
            metadata = payload(await call("inspect_checkpoint", checkpoint))
            assert str(tmp_path) not in str(metadata) and "credential" not in str(metadata)
            assert (await call("export_checkpoint", checkpoint))["isError"]
            archive = payload(await call("export_checkpoint", checkpoint, letter="o"))
            raw = base64.b64decode(archive["archive_base64"], validate=True)
            assert hashlib.sha256(raw).hexdigest() == archive["sha256"]
            assert len(raw) == archive["byte_length"]
            upload = {
                **common,
                "request_id": str(uuid4()),
                "archive_base64": archive["archive_base64"],
            }
            before = (bridge.frame, bridge.loads, runtime.store.current())
            imported = payload(await call("import_checkpoint", upload, letter="o"))
            assert imported == payload(await call("import_checkpoint", upload, letter="o"))
            changed = {**upload, "archive_base64": base64.b64encode(raw + b"changed").decode()}
            assert (await call("import_checkpoint", changed, letter="o"))["structuredContent"][
                "error"
            ]["code"] == "request_id_conflict"
            assert before == (bridge.frame, bridge.loads, runtime.store.current())
            invalid = await call(
                "import_checkpoint",
                {**upload, "request_id": str(uuid4()), "archive_base64": "!!!!"},
                letter="o",
            )
            assert invalid["structuredContent"]["error"]["code"] == "invalid_request"
            corrupt = await call(
                "import_checkpoint",
                {**upload, "request_id": str(uuid4()), "archive_base64": "YmFk"},
                letter="o",
            )
            assert corrupt["structuredContent"]["error"]["code"] == "checkpoint_corrupt"
            restore = {**checkpoint, "expected_revision": 1, "request_id": str(uuid4())}
            assert (await call("restore_checkpoint", restore))["isError"]
            payload(
                await call(
                    "revoke_slot",
                    {**common, "player_slot": "slot_1", "request_id": str(uuid4())},
                    letter="o",
                )
            )
            receipt = payload(await call("restore_checkpoint", restore, letter="o"))
            done = await runtime.controller.wait_for_command(
                match_id, UUID(receipt["command_id"]), timeout=2
            )
            assert done.status is CommandStatus.COMPLETED and done.resulting_revision == 2
            assert (
                await http.get(f"/v1/matches/{match_id}", headers=headers("p"))
            ).status_code == 401
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_lifecycle_schema_validation_and_no_side_effects(tmp_path, monkeypatch):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    await controller.start()
    app = application(controller, tmp_path, monkeypatch)
    lost = False

    def losing_client(base):
        class LostResponse(base):
            async def close(self, match_id, *, request_id=None):
                nonlocal lost
                receipt = await super().close(match_id, request_id=request_id)
                if not lost:
                    lost = True
                    raise TransportError(request_id)
                return receipt

        return LostResponse

    try:
        async with mounted(app, monkeypatch, client_type=losing_client) as (call, clients, _http):
            request = {"request_id": str(uuid4())}
            created = payload(await call("create_match", request, letter="o"))
            assert payload(await call("create_match", request, letter="o")) == created
            common = {"match_id": created["match_id"]}
            assert payload(await call("list_matches", letter="o"))["matches"]
            assert payload(await call("inspect_match", common, letter="o")) == created
            before = len(clients)
            for args in (
                {"contract_version": True},
                {"contract_version": 2},
                {"operator": "forged"},
                {"contract_version": 1.0},
            ):
                error = await call("get_capabilities", args, letter="o")
                assert error["structuredContent"]["error"]["code"] == "invalid_request"
            assert (await call("create_match", {**request, "configuration": None}, letter="o"))[
                "isError"
            ]
            assert len(clients) == before
            bad = await call(
                "start_match",
                {**common, "expected_revision": True, "request_id": str(uuid4())},
                letter="o",
            )
            assert bad["structuredContent"]["error"]["code"] == "invalid_request"
            assert "error" in await call("no_such_tool", letter="o")
            closing = {**common, "request_id": str(uuid4())}
            uncertain = await call("close_match", closing, letter="o")
            assert uncertain["structuredContent"]["error"]["code"] == "outcome_unknown"
            assert uncertain["structuredContent"]["request_id"] == closing["request_id"]
            receipt = payload(await call("close_match", closing, letter="o"))
            assert (
                payload(await call("close_match", closing, letter="o"))["command_id"]
                == receipt["command_id"]
            )
            done = await controller.wait_for_command(
                UUID(common["match_id"]), UUID(receipt["command_id"]), timeout=2
            )
            assert done.status is CommandStatus.COMPLETED
            assert payload(await call("inspect_match", common, letter="o"))["lifecycle"] == "closed"
            assert payload(await call("get_readiness", letter="o"))
    finally:
        await controller.stop()


@run_async_test
async def test_wait_timeout_terminal_failure_and_capacity(memory, tmp_path, monkeypatch):
    app, runtime, _, match_id, _, _bridge = await setup(memory, tmp_path, monkeypatch)
    command_id, request_id = uuid4(), uuid4()
    terminal = False
    blocked = asyncio.Event()
    entered = asyncio.Event()
    active = 0

    def controlled_client(base):
        class Controlled(base):
            async def wait_for_command(self, match_id, command_id, *, timeout):
                raise WaitTimeout(match_id, command_id)

            async def command_status(self, match_id, command_id):
                return CommandResult(
                    match_id=match_id,
                    command_id=command_id,
                    request_id=request_id,
                    accepted_revision=1,
                    status=CommandStatus.RECOVERY_REQUIRED if terminal else CommandStatus.RUNNING,
                )

            async def readiness(self):
                nonlocal active
                active += 1
                if active == 4:
                    entered.set()
                await blocked.wait()
                return await super().readiness()

        return Controlled

    try:
        async with mounted(app, monkeypatch, client_type=controlled_client) as (call, _, _http):
            args = {
                "match_id": str(match_id),
                "command_id": str(command_id),
                "timeout_seconds": 0.1,
            }
            waited = payload(await call("wait_for_command", args))
            assert waited["timed_out"] and waited["command"]["status"] == "running"
            terminal = True
            waited = payload(await call("wait_for_command", args))
            assert not waited["timed_out"] and waited["command"]["status"] == "recovery_required"
            assert (await call("wait_for_command", {**args, "timeout_seconds": 61}))["isError"]
            payload(await call("get_capabilities", letter="o"))
            tasks = [asyncio.create_task(call("get_readiness", letter="o")) for _ in range(4)]
            try:
                await asyncio.wait_for(entered.wait(), 2)
                over = await call("get_capabilities", letter="o")
                assert over["structuredContent"]["error"]["code"] == "capacity_exceeded"
            finally:
                blocked.set()
                await asyncio.gather(*tasks)
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_mcp_archive_and_path_bounds_before_sdk(memory, tmp_path, monkeypatch):
    from aw2_lab.mcp_tools import MAX_ARCHIVE_BASE64

    app, runtime, _, match_id, _, _bridge = await setup(memory, tmp_path, monkeypatch)
    try:
        async with mounted(app, monkeypatch) as (call, clients, _http):
            too_large = await call(
                "import_checkpoint",
                {
                    "match_id": str(match_id),
                    "request_id": str(uuid4()),
                    "archive_base64": "A" * (MAX_ARCHIVE_BASE64 + 4),
                },
                letter="o",
            )
            assert too_large["structuredContent"]["error"]["code"] == "invalid_request"
            assert not clients
            bad_path = await call(
                "move_wait",
                {
                    "match_id": str(match_id),
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "unit_id": "1",
                    "path": [{"x": 1, "y": 1}] * 4097,
                },
            )
            assert bad_path["structuredContent"]["error"]["code"] == "invalid_request"
            assert not clients
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_queued_start_receipt_and_stale_revision(memory, tmp_path, monkeypatch):
    from test_playable_runtime import setup as runtime_setup

    runtime, _, match_id, _, bridge = await runtime_setup(memory, tmp_path)
    app = application(runtime.controller, tmp_path, monkeypatch)
    runtime._session_changed = lambda service: setattr(
        app.state, "match_checkpoint_service", service
    )
    try:
        async with mounted(app, monkeypatch) as (call, _, _http):
            args = {"match_id": str(match_id), "request_id": str(uuid4()), "expected_revision": 0}
            assert (await call("start_match", args))["structuredContent"]["error"][
                "code"
            ] == "permission_denied"
            receipt = payload(await call("start_match", args, letter="o"))
            assert (
                payload(await call("start_match", args, letter="o"))["command_id"]
                == receipt["command_id"]
            )
            done = await runtime.controller.wait_for_command(
                match_id, UUID(receipt["command_id"]), timeout=2
            )
            assert done.status is CommandStatus.COMPLETED and bridge.boot_calls == 1
            stale = await call("create_checkpoint", {**args, "request_id": str(uuid4())})
            if stale["isError"]:
                assert stale["structuredContent"]["error"]["code"] == "stale_revision"
            else:
                failed = await runtime.controller.wait_for_command(
                    match_id, UUID(stale["structuredContent"]["command_id"]), timeout=2
                )
                assert failed.error.code.value == "stale_revision"
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_python_mcp_host_max_archive_envelopes(memory, tmp_path, monkeypatch):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from aw2_lab.checkpoint_store import MAX_ARCHIVE_BYTES

    app, runtime, _, match_id, _, _bridge = await setup(memory, tmp_path, monkeypatch)
    raw = b"x" * MAX_ARCHIVE_BYTES

    def export_client(base):
        class Export(base):
            async def export_checkpoint(self, match_id, checkpoint_id):
                return raw

        return Export

    try:
        async with (
            mounted(app, monkeypatch, client_type=export_client),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://localhost",
                headers={"Authorization": "Bearer " + "o" * 43},
            ) as host_http,
            streamable_http_client("http://localhost/mcp/", http_client=host_http) as (
                read,
                write,
                _session_id,
            ),
            ClientSession(read, write) as host,
        ):
            await host.initialize()
            exported = await host.call_tool(
                "export_checkpoint", {"match_id": str(match_id), "checkpoint_id": str(uuid4())}
            )
            assert not exported.isError
            assert (
                base64.b64decode(exported.structuredContent["archive_base64"], validate=True) == raw
            )
            rejected = await host.call_tool(
                "import_checkpoint",
                {
                    "match_id": str(match_id),
                    "request_id": str(uuid4()),
                    "archive_base64": base64.b64encode(raw).decode(),
                },
            )
            assert rejected.isError
            assert rejected.structuredContent["error"]["code"] == "checkpoint_corrupt"
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_authorized_state_command_resources_and_coherent_screenshot(
    memory, tmp_path, monkeypatch
):
    import json

    app, runtime, _, match_id, _, bridge = await setup(memory, tmp_path, monkeypatch)
    command_id = None
    png = b"\x89PNG\r\n\x1a\ncoherent"

    async def screenshot(_observation):
        return png

    runtime.controller.set_screenshot_provider(screenshot)

    class EndTurnExecutor:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(runtime_module, "EndTurnActionExecutor", EndTurnExecutor)
    try:
        async with mounted(app, monkeypatch) as (call, _, _http):
            state_uri = f"aw2://v1/matches/{match_id}/state"
            state_result = await call("_resource_read", {"uri": state_uri})
            initial = json.loads(state_result["contents"][0]["text"])
            assert initial["settled"] is True
            assert "observation" in initial
            assert payload(await call("get_state", {"match_id": str(match_id)})) == initial
            power_receipt = payload(
                await call(
                    "activate_normal_power",
                    {
                        "match_id": str(match_id),
                        "expected_revision": initial["summary"]["revision"],
                        "request_id": str(uuid4()),
                    },
                )
            )
            await runtime.controller.wait_for_command(
                match_id, UUID(power_receipt["command_id"]), timeout=2
            )
            power_result = payload(
                await call(
                    "wait_for_command",
                    {
                        "match_id": str(match_id),
                        "command_id": power_receipt["command_id"],
                        "timeout_seconds": 2,
                    },
                )
            )
            assert power_result["command"]["status"] == "rejected"
            assert power_result["command"]["error"]["code"] == "unsupported_feature"
            super_receipt = payload(
                await call(
                    "activate_super_power",
                    {
                        "match_id": str(match_id),
                        "expected_revision": initial["summary"]["revision"],
                        "request_id": str(uuid4()),
                    },
                )
            )
            super_result = payload(
                await call(
                    "wait_for_command",
                    {
                        "match_id": str(match_id),
                        "command_id": super_receipt["command_id"],
                        "timeout_seconds": 2,
                    },
                )
            )
            assert super_result["command"]["status"] in {
                "rejected",
                "completed",
                "rolled_back",
                "recovery_required",
            }
            actions_before = bridge.frame
            request_id = str(uuid4())
            receipt = payload(
                await call(
                    "end_turn",
                    {
                        "match_id": str(match_id),
                        "expected_revision": initial["summary"]["revision"],
                        "request_id": request_id,
                    },
                )
            )
            command_id = receipt["command_id"]
            await runtime.controller.wait_for_command(match_id, UUID(command_id), timeout=2)
            command_uri = f"aw2://v1/matches/{match_id}/commands/{command_id}"
            status = json.loads(
                (await call("_resource_read", {"uri": command_uri}))["contents"][0]["text"]
            )
            assert status["status"] == "completed"
            state = payload(await call("get_state", {"match_id": str(match_id)}))
            assert state["summary"]["revision"] == initial["summary"]["revision"] + 1
            assert state["settled"] and bridge.frame == actions_before + 1
            screenshot_result = await call(
                "get_screenshot",
                {"match_id": str(match_id), "revision": state["summary"]["revision"]},
            )
            metadata = screenshot_result["structuredContent"]
            assert metadata == {
                "contract_version": 1,
                "match_id": str(match_id),
                "revision": state["summary"]["revision"],
                "frame": state["observation"]["game_state"]["frame"],
                "mime_type": "image/png",
            }
            assert base64.b64decode(screenshot_result["content"][0]["data"]) == png
            again = json.loads(
                (await call("_resource_read", {"uri": state_uri}))["contents"][0]["text"]
            )
            assert again == state and bridge.frame == actions_before + 1
            assert "error" in await call(
                "_resource_read", {"uri": f"aw2://v1/matches/{uuid4()}/state"}
            )
            unavailable = await call(
                "get_screenshot",
                {"match_id": str(match_id), "revision": state["summary"]["revision"] - 1},
            )
            assert (
                unavailable["isError"]
                and unavailable["structuredContent"]["error"]["code"] == "observation_unavailable"
            )
            assert bridge.frame == actions_before + 1
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_operator_debug_tools_opt_in_bounds_and_restore(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, monkeypatch)
    app.state.playable_runtime = runtime
    try:
        async with mounted(app, monkeypatch) as (call, _, _http):
            current = await public.state(operator, match_id)
            player = await call(
                "debug_read_memory",
                {
                    "match_id": str(match_id),
                    "expected_revision": current.summary.revision,
                    "address": 0x02000000,
                    "length": 8,
                },
                letter="p",
            )
            assert player["structuredContent"]["error"]["code"] == "permission_denied"
            disabled = await call(
                "debug_advance_frames",
                {
                    "match_id": str(match_id),
                    "expected_revision": current.summary.revision,
                    "request_id": str(uuid4()),
                    "frames": 1,
                },
                letter="o",
            )
            assert disabled["structuredContent"]["error"]["code"] == "unsupported_feature"
            public.authorization.debug_enabled = True
            current = await public.state(operator, match_id)
            checkpoint_receipt = payload(
                await call(
                    "create_checkpoint",
                    {
                        "match_id": str(match_id),
                        "expected_revision": current.summary.revision,
                        "request_id": str(uuid4()),
                    },
                    letter="o",
                )
            )
            checkpoint_result = await runtime.controller.wait_for_command(
                match_id, UUID(checkpoint_receipt["command_id"]), timeout=2
            )
            assert checkpoint_result.status is CommandStatus.COMPLETED
            read = payload(
                await call(
                    "debug_read_memory",
                    {
                        "match_id": str(match_id),
                        "expected_revision": current.summary.revision,
                        "address": 0x02000000,
                        "length": 8,
                    },
                    letter="o",
                )
            )
            assert (
                read["match_id"] == str(match_id) and read["revision"] == current.summary.revision
            )
            assert len(base64.b64decode(read["data"], validate=True)) == 8
            for name, fields in (
                ("debug_press_buttons", {"buttons": ["neutral"], "frames": 1}),
                ("debug_advance_frames", {"frames": 1}),
                ("debug_write_memory", {"address": 0x02000000, "data": "AQ=="}),
                ("debug_reset", {}),
            ):
                current = await public.state(operator, match_id)
                receipt = payload(
                    await call(
                        name,
                        {
                            "match_id": str(match_id),
                            "expected_revision": current.summary.revision,
                            "request_id": str(uuid4()),
                            **fields,
                        },
                        letter="o",
                    )
                )
                result = await runtime.controller.wait_for_command(
                    match_id, UUID(receipt["command_id"]), timeout=2
                )
                assert result.status is CommandStatus.RECOVERY_REQUIRED
                unavailable = await public.state(operator, match_id)
                assert unavailable.summary.revision == current.summary.revision + 1
                assert unavailable.observation.identity_status.value == "unavailable"
                checkpoint = runtime.store.current()
                restored = payload(
                    await call(
                        "restore_checkpoint",
                        {
                            "match_id": str(match_id),
                            "checkpoint_id": str(checkpoint.checkpoint_id),
                            "expected_revision": unavailable.summary.revision,
                            "request_id": str(uuid4()),
                        },
                        letter="o",
                    )
                )
                restored_result = await runtime.controller.wait_for_command(
                    match_id, UUID(restored["command_id"]), timeout=2
                )
                assert restored_result.status is CommandStatus.COMPLETED
            bad_frames = await call(
                "debug_advance_frames",
                {
                    "match_id": str(match_id),
                    "expected_revision": 5,
                    "request_id": str(uuid4()),
                    "frames": 601,
                },
                letter="o",
            )
            assert bad_frames["structuredContent"]["error"]["code"] == "invalid_request"
            bad_address = await call(
                "debug_read_memory",
                {
                    "match_id": str(match_id),
                    "expected_revision": (await public.state(operator, match_id)).summary.revision,
                    "address": 0x08000000,
                    "length": 1,
                },
                letter="o",
            )
            assert bad_address["isError"]
            assert bridge.resets >= 2
    finally:
        await runtime.controller.stop()
