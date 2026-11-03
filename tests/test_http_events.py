"""Exercise incremental SSE ASGI delivery without buffering the entire HTTP response."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from test_authorization import token
from test_http_api import application, client_for, headers
from test_match_controller import run_async_test

from aw2_lab.api import event_stream
from aw2_lab.api_contract import CreateMatchRequest, IssueInvitationRequest, JoinSlotRequest
from aw2_lab.authorization import AuthorizationService
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.match_contract import PlayerSlot
from aw2_lab.match_controller import MatchController


@asynccontextmanager
async def stream(app, path, *, authorization="p", cursor=None):
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    await incoming.put({"type": "http.request", "body": b""})
    request_headers = []
    if authorization:
        request_headers.append((b"authorization", f"Bearer {authorization * 43}".encode()))
    if cursor is not None:
        request_headers.append((b"last-event-id", cursor.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": request_headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 43127),
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, incoming.get, outgoing.put))
    try:
        async with asyncio.timeout(2):
            started = await outgoing.get()
        yield started, outgoing
    finally:
        await incoming.put({"type": "http.disconnect"})
        try:
            async with asyncio.timeout(2):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def event(outgoing):
    async with asyncio.timeout(2):
        message = await outgoing.get()
    body = message["body"].decode()
    fields = dict(line.split(": ", 1) for line in body.strip().splitlines())
    payload = json.loads(fields["data"])
    assert fields["id"] == payload["event_id"]
    assert fields["event"] == payload["event"]
    assert payload["contract_version"] == 1
    return payload


async def setup(tmp_path, monkeypatch):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    await controller.start()
    service = AuthorizedMatchService(controller)
    operator = service.authenticate(token("o"))
    match = await service.create(operator, CreateMatchRequest(request_id=uuid4()))
    for slot, letter, invitation in ((PlayerSlot.SLOT_1, "p", "i"), (PlayerSlot.SLOT_2, "q", "j")):
        await service.invite(
            operator,
            match.match_id,
            slot,
            IssueInvitationRequest(request_id=uuid4(), invitation_token=token(invitation)),
        )
        await service.join(
            match.match_id,
            slot,
            token(letter),
            JoinSlotRequest(
                request_id=uuid4(), invitation_token=token(invitation), display_name=letter
            ),
        )
    return application(controller, tmp_path, monkeypatch), service, match.match_id, operator


@run_async_test
async def test_http_sse_live_replay_auth_and_disconnect_cleanup(tmp_path, monkeypatch):
    app, service, match_id, operator = await setup(tmp_path, monkeypatch)
    path = f"/v1/matches/{match_id}/events"
    try:
        async with client_for(app) as client:
            caps = (await client.get("/v1/capabilities")).json()
            assert caps["http_sse"]["implemented"] and caps["http_sse"]["available"]
            for credential, status in ((None, 401), ("x", 401)):
                async with stream(app, path, authorization=credential) as (started, _):
                    assert started["status"] == status
            async with stream(app, f"/v1/matches/{uuid4()}/events") as (started, _):
                assert started["status"] == 403
            async with stream(app, path, cursor="x" * 129) as (started, _):
                assert started["status"] == 422
            schema = (await client.get("/openapi.json")).json()
            assert (
                "text/event-stream"
                in schema["paths"]["/v1/matches/{match_id}/events"]["get"]["responses"]["200"][
                    "content"
                ]
            )
        async with stream(app, path) as (started, output):
            assert started["status"] == 200
            response_headers = dict(started["headers"])
            assert response_headers[b"content-type"].startswith(b"text/event-stream")
            assert response_headers[b"cache-control"] == b"no-store"
            assert response_headers[b"x-accel-buffering"] == b"no"
            first = await event(output)
            assert first["event"] == "snapshot" and first["resync"] is False
            cursor = first["event_id"]
            await service.revoke(operator, match_id, PlayerSlot.SLOT_2, uuid4())
            updated = await event(output)
            assert updated["event"] == "match.updated"
            assert updated["payload"]["summary"]["slots"][1]["status"] == "revoked"
            assert "p" * 43 not in json.dumps(updated) and "i" * 43 not in json.dumps(updated)
        channel = service.controller.events._channels[match_id]
        assert not channel.subscribers
        async with stream(app, path, cursor=cursor) as (_, output):
            assert await event(output) == updated
        # Revoked callers cannot replay, even with a retained cursor.
        async with stream(app, path, authorization="q", cursor=cursor) as (started, _):
            assert started["status"] == 401
        async with stream(app, path, cursor="unknown") as (_, output):
            assert (await event(output))["resync"] is True
        async with stream(app, path) as (_, output):
            await event(output)
            await service.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
            async with asyncio.timeout(2):
                final = await output.get()
            assert final["body"] == b"" and not final.get("more_body", False)
        assert not channel.subscribers
        assert not any(service.authorization._changed.values())
    finally:
        await service.controller.stop()


@run_async_test
async def test_closed_http_stream_sends_one_snapshot_and_ends(tmp_path, monkeypatch):
    app, service, match_id, operator = await setup(tmp_path, monkeypatch)
    try:
        receipt = await service.close(operator, match_id, uuid4())
        await service.wait_for_command(operator, match_id, receipt.command_id, timeout=1)
        async with client_for(app) as client:
            response = await client.get(f"/v1/matches/{match_id}/events", headers=headers("p"))
            assert response.status_code == 200
            assert response.text.count("event: snapshot") == 1
            assert '"lifecycle":"closed"' in response.text
    finally:
        await service.controller.stop()


@run_async_test
async def test_heartbeats_do_not_advance_cursor_and_shutdown_closes_idle_stream(
    tmp_path, monkeypatch
):
    app, service, match_id, _ = await setup(tmp_path, monkeypatch)
    monkeypatch.setattr(event_stream, "ApiLimits", lambda: SimpleNamespace(heartbeat_seconds=0.01))
    try:
        async with stream(app, f"/v1/matches/{match_id}/events") as (_, output):
            snapshot = await event(output)
            async with asyncio.timeout(2):
                heartbeat = await output.get()
            assert heartbeat["body"] == b": heartbeat\n\n"
            assert service.controller.events._channels[match_id].cursor == snapshot["event_id"]
            await service.controller.stop()
            async with asyncio.timeout(2):
                while True:
                    message = await output.get()
                    if not message.get("more_body", False):
                        assert message["body"] == b""
                        break
        assert not service.controller.events._channels[match_id].subscribers
        assert not any(service.authorization._changed.values())
    finally:
        await service.controller.stop()
