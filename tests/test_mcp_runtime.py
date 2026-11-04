"""MCP application lifecycle and shared HTTP/SDK/SSE integration, without a ROM."""

import asyncio

import httpx
import pytest
from test_authorization import token
from test_health import FakeLauncher
from test_http_events import event, setup, stream
from test_mcp_authorization import headers, result, rpc

from aw2_lab import mcp_runtime
from aw2_lab.api import app as app_module
from aw2_lab.authorization import AuthorizationError, AuthorizationService
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.emulator import EmulatorSettings
from aw2_lab.match_controller import MatchController
from aw2_lab.mcp_auth import MCPCaller
from aw2_lab.mcp_runtime import MCPAdapterRuntime, api_url_for_bind
from aw2_lab.rom_profile import AW2_US_REVISION_0
from aw2_lab.sdk import AsyncAW2Client, TransportError


@pytest.mark.anyio
async def test_mcp_http_sdk_and_sse_share_application(tmp_path, monkeypatch):
    app, service, match_id, operator = await setup(tmp_path, monkeypatch)
    runtime = app.state.mcp_runtime
    clients = []

    class LocalClient(AsyncAW2Client):
        def __init__(self, base_url, *, credential):
            assert base_url == runtime.api_base_url
            super().__init__(
                base_url, credential=credential, transport=httpx.ASGITransport(app=app)
            )
            clients.append(self)

    monkeypatch.setattr(mcp_runtime, "AsyncAW2Client", LocalClient)
    assert runtime.controller is service.controller
    assert runtime.events is service.controller.events
    assert runtime.matches is app.state.authorized_matches
    assert not runtime.running
    async with app.router.lifespan_context(app):
        assert runtime.running
        assert app.state.mcp_server.session_manager.session_idle_timeout == 1800
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as http:
            assert (await http.get("/health")).status_code == 200
            async with stream(app, f"/v1/matches/{match_id}/events") as (started, outgoing):
                assert started["status"] == 200
                assert (await event(outgoing))["event"] == "snapshot"
                initialize = rpc(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                for letter in ("o", "p"):
                    response = await http.post("/mcp/", headers=headers(letter), json=initialize)
                    assert result(response)["result"]
                    session = response.headers["mcp-session-id"]
                    h = headers(letter, session)
                    await http.post(
                        "/mcp/",
                        headers=h,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    )
                    catalog = result(await http.post("/mcp/", headers=h, json=rpc("tools/list")))
                    assert [tool["name"] for tool in catalog["result"]["tools"]] == [
                        "get_capabilities"
                    ]
                    call = rpc("tools/call", {"name": "get_capabilities", "arguments": {}})
                    response = result(await http.post("/mcp/", headers=h, json=call))["result"]
                    direct = (await http.get("/v1/capabilities")).json()
                    assert response["structuredContent"] == direct
                    assert not any(action["available"] for action in direct["actions"])
                    before = len(clients)
                    bad = rpc(
                        "tools/call",
                        {"name": "get_capabilities", "arguments": {"contract_version": 2}},
                    )
                    assert result(await http.post("/mcp/", headers=h, json=bad))["result"][
                        "isError"
                    ]
                    assert len(clients) == before
                assert (await http.get("/v1/readiness", headers=headers())).status_code == 200
                assert (await service.state(operator, match_id)).summary.match_id == match_id
    assert not runtime.running
    assert all(client._http.is_closed for client in clients)
    assert len(clients) == 2
    assert clients[0]._http.headers["Authorization"] == "Bearer " + "o" * 43
    assert clients[1]._http.headers["Authorization"] == "Bearer " + "p" * 43
    assert not any(service.authorization._changed.values())


def make_runtime(tmp_path, *, cleanup_timeout=1):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    service = AuthorizedMatchService(controller)
    runtime = MCPAdapterRuntime(
        controller,
        lambda: service,
        api_base_url="http://localhost:45678",
        cleanup_timeout=cleanup_timeout,
    )
    return runtime, MCPCaller(auth, auth.authenticate(token("o")), token("o"))


@pytest.mark.anyio
async def test_shutdown_cancels_pending_work_closes_connections_and_unsubscribes(tmp_path):
    runtime, caller = make_runtime(tmp_path)
    entered = asyncio.Event()
    cleaned = []
    clients = []

    async def pending():
        async with runtime.operation(caller) as cleanup:
            cleanup.callback(cleaned.append, "subscription")
            async with runtime.sdk(caller) as client:
                clients.append(client)
                entered.set()
                await asyncio.Event().wait()

    with pytest.raises(AuthorizationError):
        async with runtime.sdk(caller):
            pass
    async with runtime.run():
        task = asyncio.create_task(pending())
        await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(AuthorizationError):
        await task
    assert cleaned == ["subscription"]
    assert clients[0]._http.is_closed
    assert not runtime._active
    with pytest.raises(AuthorizationError):
        async with runtime.sdk(caller):
            pass


@pytest.mark.anyio
async def test_client_failure_and_disconnect_release_leases(tmp_path, monkeypatch):
    runtime, caller = make_runtime(tmp_path)
    clients = []

    def fail(request):
        raise httpx.ConnectError("unavailable", request=request)

    class DisconnectedClient(AsyncAW2Client):
        def __init__(self, base_url, *, credential):
            super().__init__(
                base_url, credential=credential, transport=httpx.MockTransport(fail), retries=0
            )
            clients.append(self)

    monkeypatch.setattr(mcp_runtime, "AsyncAW2Client", DisconnectedClient)
    async with runtime.run():
        with pytest.raises(TransportError, match="HTTP request failed"):
            async with runtime.sdk(caller) as client:
                await client.capabilities()
        entered = asyncio.Event()

        async def disconnected():
            async with runtime.sdk(caller):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(disconnected())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not runtime._active
    assert all(client._http.is_closed for client in clients)


@pytest.mark.anyio
async def test_startup_failure_stops_emulator_and_controller(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "select_rom_profile", lambda _: AW2_US_REVISION_0)

    class FailedLauncher(FakeLauncher):
        async def start(self):
            raise RuntimeError("synthetic startup failure")

    launcher = FailedLauncher()
    controller = MatchController()
    app = app_module.create_app(
        settings=EmulatorSettings(rom_path=tmp_path / "rom.gba"),
        launcher=launcher,
        match_controller=controller,
        storage_root=tmp_path / "data",
    )
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup must fail")
    assert launcher.stopped
    assert controller._stopped
    assert not app.state.mcp_runtime.running


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("0.0.0.0", "http://127.0.0.1:45678"),
        ("::", "http://[::1]:45678"),
        ("localhost", "http://localhost:45678"),
    ],
)
def test_configured_api_url(host, url):
    assert api_url_for_bind(host, 45678) == url


@pytest.mark.anyio
async def test_idle_sessions_expire_and_reinitialize(tmp_path):
    from aw2_lab.mcp import create_mcp_server
    from aw2_lab.mcp_auth import MCPAuthorizationBoundary

    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    server = create_mcp_server()
    server.session_manager.session_idle_timeout = 0.02
    app = MCPAuthorizationBoundary(server.streamable_http_app(), auth)
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as http,
    ):
        initialize = rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        response = await http.post("/", headers=headers(), json=initialize)
        assert result(response)["result"]
        old = response.headers["mcp-session-id"]
        await asyncio.sleep(0.1)
        assert (
            await http.post("/", headers=headers(session=old), json=rpc("tools/list"))
        ).status_code == 404
        response = await http.post("/", headers=headers(), json=initialize)
        assert result(response)["result"]
        assert response.headers["mcp-session-id"] != old


@pytest.mark.anyio
async def test_stalled_cleanup_is_bounded_and_reported(tmp_path):
    runtime, caller = make_runtime(tmp_path, cleanup_timeout=0.02)

    async def stalled_cleanup():
        await asyncio.Event().wait()

    with pytest.raises(RuntimeError, match="MCP operation cleanup deadline expired"):
        async with runtime.run():
            with pytest.raises(RuntimeError, match="MCP operation cleanup deadline expired"):
                async with runtime.operation(caller) as cleanup:
                    cleanup.push_async_callback(stalled_cleanup)
    assert not runtime.running
    assert not runtime._active
