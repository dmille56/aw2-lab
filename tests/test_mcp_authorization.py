"""Exercise authenticated MCP sessions through the actual Streamable HTTP app."""

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from test_authorization import claim, create, invite, token

from aw2_lab.authorization import AuthorizationError, AuthorizationService, Permission
from aw2_lab.match_contract import PlayerSlot
from aw2_lab.mcp import create_mcp_server
from aw2_lab.mcp_auth import MCPAuthorizationBoundary, MCPCaller, caller_from_request


def headers(letter="o", session=None, **extra):
    return {
        "Authorization": f"Bearer {letter * 43}",
        "Accept": "application/json, text/event-stream",
        **({"Mcp-Session-Id": session, "MCP-Protocol-Version": "2025-11-25"} if session else {}),
        **extra,
    }


def rpc(method, params=None, identifier=1):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}


def result(response):
    assert response.status_code == 200, response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        return json.loads(
            next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        )
    return response.json()


@pytest.fixture
def auth(tmp_path):
    return AuthorizationService(tmp_path / "auth.json", token("o"))


@pytest.mark.anyio
async def test_mounted_authentication_sessions_origins_and_revocation(auth):
    summary = create(auth)
    invite(auth, summary.match_id)
    claim(auth, summary.match_id)
    invite(auth, summary.match_id, PlayerSlot.SLOT_2, secret=token("j"))
    claim(auth, summary.match_id, PlayerSlot.SLOT_2, invitation=token("j"), credential=token("q"))
    server = create_mcp_server()

    @server.tool()
    def permission_probe(permission: Permission, match_id: UUID) -> str:
        caller = caller_from_request(server.get_context().request_context.request)
        caller.check(permission, match_id)
        return caller.principal.kind

    @server.resource("aw2://v1/matches/{match_id}/state")
    def resource_probe(match_id: str) -> str:
        caller = caller_from_request(server.get_context().request_context.request)
        caller.check(Permission.READ, UUID(match_id))
        return "authorized state"

    app = MCPAuthorizationBoundary(server.streamable_http_app(), auth)
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        initialize = rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert (await client.post("/", json=initialize)).status_code == 401
        assert (await client.post("/", headers=headers("x"), json=initialize)).status_code == 401
        rejected = await client.post(
            "/", headers=headers(Origin="https://evil.invalid"), json=initialize
        )
        assert rejected.status_code == 403
        assert (
            await client.post("/", headers=headers(Host="evil.invalid"), json=initialize)
        ).status_code == 421
        response = await client.post("/", headers=headers("p"), json=initialize)
        assert result(response)["result"]["serverInfo"]["name"] == "aw2-lab"
        session = response.headers["mcp-session-id"]
        player = headers("p", session)
        assert (
            await client.post(
                "/", headers=player, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        ).status_code == 202
        call = rpc("tools/call", {"name": "hello_world", "arguments": {}})
        assert (
            result(await client.post("/", headers=player, json=call))["result"]["isError"] is False
        )
        assert (await client.post("/", headers=headers("q", session), json=call)).status_code == 404
        assert (await client.post("/", headers=headers("o", session), json=call)).status_code == 404
        assert (await client.get("/", headers={"Mcp-Session-Id": session})).status_code == 401
        for permission in ("admin", "archive", "debug"):
            probe = rpc(
                "tools/call",
                {
                    "name": "permission_probe",
                    "arguments": {
                        "permission": permission,
                        "match_id": str(summary.match_id),
                    },
                },
            )
            assert result(await client.post("/", headers=player, json=probe))["result"]["isError"]
        own = rpc("resources/read", {"uri": f"aw2://v1/matches/{summary.match_id}/state"})
        assert "authorized state" in str(result(await client.post("/", headers=player, json=own)))
        foreign = rpc("resources/read", {"uri": f"aw2://v1/matches/{uuid4()}/state"})
        assert "error" in result(await client.post("/", headers=player, json=foreign))
        discovery = result(await client.post("/", headers=player, json=rpc("tools/list")))
        assert all(letter * 43 not in str(discovery) for letter in "opqij")
        operator = auth.authenticate(token("o"))
        auth.revoke_slot(operator, summary.match_id, PlayerSlot.SLOT_1, uuid4())
        assert (await client.post("/", headers=player, json=call)).status_code == 401
        # An unaffected player can still initialize an independent session.
        assert result(await client.post("/", headers=headers("q"), json=initialize))["result"]
        assert all(letter * 43 not in rejected.text for letter in "opq")


@pytest.mark.anyio
async def test_missing_provisioning_remote_peer_and_direct_tool_are_denied():
    server = create_mcp_server()
    app = MCPAuthorizationBoundary(server.streamable_http_app(), None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (
            await client.post("/", headers=headers(), json=rpc("initialize"))
        ).status_code == 503
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 123)),
        base_url="http://localhost",
    ) as client:
        assert (
            await client.post("/", headers=headers(), json=rpc("initialize"))
        ).status_code == 403
    with pytest.raises(ToolError, match="Context is not available"):
        await server.call_tool("hello_world", {})


@pytest.mark.anyio
async def test_revocation_wakes_pending_transport_and_releases_watch(auth):
    summary = create(auth)
    invite(auth, summary.match_id)
    claim(auth, summary.match_id)
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def waiting_app(scope, receive, send):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    app = MCPAuthorizationBoundary(waiting_app, auth)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        pending = asyncio.create_task(client.get("/", headers=headers("p")))
        await asyncio.wait_for(started.wait(), 1)
        auth.revoke_slot(
            auth.authenticate(token("o")), summary.match_id, PlayerSlot.SLOT_1, uuid4()
        )
        response = await asyncio.wait_for(pending, 1)
        assert response.status_code == 401
        assert stopped.is_set()
        assert not any(auth._changed.values())


def test_caller_permission_guard_and_revoked_cached_identity(auth):
    summary = create(auth)
    invite(auth, summary.match_id)
    claim(auth, summary.match_id)
    caller = MCPCaller(auth, auth.authenticate(token("p")), token("p"))
    caller.check(Permission.READ, summary.match_id)
    for permission in (Permission.ADMIN, Permission.ARCHIVE, Permission.DEBUG):
        with pytest.raises(AuthorizationError):
            caller.check(permission, summary.match_id)
    with pytest.raises(AuthorizationError):
        caller.check(Permission.READ, uuid4())
    operator = MCPCaller(auth, auth.authenticate(token("o")), token("o"))
    with pytest.raises(AuthorizationError):
        operator.check(Permission.PLAY, summary.match_id)
    with pytest.raises(AuthorizationError):
        operator.check(Permission.DEBUG, summary.match_id)
    auth.revoke_slot(operator.principal, summary.match_id, PlayerSlot.SLOT_1, uuid4())
    with pytest.raises(AuthorizationError):
        caller.check()
    assert "p" * 43 not in repr(caller)


@pytest.mark.anyio
async def test_delivery_recheck_stops_started_stream(auth):
    summary = create(auth)
    invite(auth, summary.match_id)
    claim(auth, summary.match_id)
    started = asyncio.Event()

    async def streaming(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"initial", "more_body": True})
        started.set()
        await asyncio.Event().wait()
        await send({"type": "http.response.body", "body": b"private"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MCPAuthorizationBoundary(streaming, auth)),
        base_url="http://localhost",
    ) as client:
        pending = asyncio.create_task(client.get("/", headers=headers("p")))
        await asyncio.wait_for(started.wait(), 1)
        auth.revoke_slot(
            auth.authenticate(token("o")), summary.match_id, PlayerSlot.SLOT_1, uuid4()
        )
        response = await asyncio.wait_for(pending, 1)
        assert response.content == b"initial"
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_pending_operation_wakes_and_cached_result_is_not_returned(auth):
    summary = create(auth)
    invite(auth, summary.match_id)
    claim(auth, summary.match_id)
    caller = MCPCaller(auth, auth.authenticate(token("p")), token("p"))
    entered = asyncio.Event()

    async def operation():
        async with caller.operation(Permission.READ, summary.match_id):
            entered.set()
            await asyncio.Event().wait()
        return "cached result"

    pending = asyncio.create_task(operation())
    await asyncio.wait_for(entered.wait(), 1)
    auth.revoke_slot(auth.authenticate(token("o")), summary.match_id, PlayerSlot.SLOT_1, uuid4())
    with pytest.raises(AuthorizationError):
        await asyncio.wait_for(pending, 1)
    assert not any(auth._changed.values())
