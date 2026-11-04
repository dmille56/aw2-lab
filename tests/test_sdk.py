"""Public SDK retries, event recovery, wait semantics, and real HTTP composition."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from test_authorization import token
from test_http_api import application
from test_http_gameplay_checkpoints import setup
from test_match_controller import run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab.api_contract import VERIFIED_CONFIGURATION
from aw2_lab.match_contract import CommandResult, CommandStatus, EndTurnAction, PlayerSlot
from aw2_lab.match_events import SnapshotEvent
from aw2_lab.sdk import APIError, AsyncAW2Client, ProtocolError, TransportError, WaitTimeout


@run_async_test
async def test_sdk_retries_preserve_ids_bodies_and_null_configuration_rules(tmp_path, monkeypatch):
    from aw2_lab.authorization import AuthorizationService
    from aw2_lab.match_controller import MatchController

    controller = MatchController(
        authorization=AuthorizationService(tmp_path / "auth.json", token("o"))
    )
    app = application(controller, tmp_path, monkeypatch)
    requests = []
    inner = httpx.ASGITransport(app=app)

    async def handler(request):
        requests.append(request.content)
        if len(requests) == 1:
            # Execute the request but lose the response to exercise durable deduplication.
            await inner.handle_async_request(request)
            raise httpx.ReadError("lost response")
        return await inner.handle_async_request(request)

    identifier = uuid4()
    async with AsyncAW2Client(
        credential=token("o"), transport=httpx.MockTransport(handler), retry_delay=0.001
    ) as sdk:
        summary = await sdk.create_match(VERIFIED_CONFIGURATION, request_id=identifier)
        assert summary.configuration == VERIFIED_CONFIGURATION
        assert requests[0] == requests[1]
        assert json.loads(requests[1])["request_id"] == str(identifier)
        assert json.loads(requests[1])["configuration"]["rules"]["capture_limit"] is None
        assert len((await sdk.list_matches()).matches) == 1
    await inner.aclose()


@run_async_test
async def test_sdk_real_http_play_checkpoint_restore_and_errors(memory, tmp_path, monkeypatch):
    app, runtime, _public, match_id, _operator, _ = await setup(memory, tmp_path, monkeypatch)
    from aw2_lab import playable_runtime as runtime_module
    from aw2_lab.match_contract import MatchLifecycle
    from aw2_lab.match_controller import MutationOutcome

    class Executor:
        def __init__(self, navigator, tracker):
            self.tracker = tracker

        async def execute(self, request, observation):
            runtime.bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await runtime.bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(runtime_module, "EndTurnActionExecutor", Executor)
    try:
        async with (
            AsyncAW2Client(credential=token("o"), transport=httpx.ASGITransport(app=app)) as admin,
            AsyncAW2Client(credential=token("p"), transport=httpx.ASGITransport(app=app)) as red,
            AsyncAW2Client(credential=token("q"), transport=httpx.ASGITransport(app=app)) as blue,
        ):
            assert (await red.state(match_id)).observation.revision == 1
            saved = await red.create_checkpoint(match_id, 1)
            await runtime.controller.wait_for_command(match_id, saved.command_id, timeout=2)
            checkpoint = (await red.wait_for_command(match_id, saved.command_id)).checkpoint_id
            assert checkpoint is not None
            archive = await admin.export_checkpoint(match_id, checkpoint)
            imported = await admin.import_checkpoint(match_id, archive)
            assert imported.checkpoint_id == checkpoint
            assert (
                await blue.inspect_checkpoint(match_id, checkpoint)
            ).checkpoint.checkpoint_id == checkpoint
            assert (await admin.list_checkpoints(match_id)).checkpoints
            receipt = await red.submit(match_id, 1, EndTurnAction())
            await runtime.controller.wait_for_command(match_id, receipt.command_id, timeout=2)
            result = await red.wait_for_command(match_id, receipt.command_id)
            assert result.status is CommandStatus.COMPLETED
            assert (await blue.observation(match_id)).observation.revision == 2
            restored = await admin.restore_checkpoint(match_id, checkpoint, 2)
            await runtime.controller.wait_for_command(match_id, restored.command_id, timeout=2)
            assert (
                await admin.wait_for_command(match_id, restored.command_id)
            ).status is CommandStatus.COMPLETED
            with pytest.raises(APIError) as denied:
                await red.close(match_id)
            assert denied.value.status == 403
            assert "p" * 43 not in str(denied.value)
    finally:
        await runtime.controller.stop()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data, *, hang=False):
        self.data = data
        self.hang = hang
        self.closed = False

    async def __aiter__(self):
        for chunk in self.data:
            yield chunk
        if self.hang:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def frame(event):
    return (
        f"id: {event.event_id}\nevent: {event.event}\ndata: {event.model_dump_json()}\n\n".encode()
    )


@run_async_test
async def test_sdk_sse_reconnect_cursor_snapshot_resync_and_wait_completion(
    memory, tmp_path, monkeypatch
):
    _app, runtime, public, match_id, operator, _ = await setup(memory, tmp_path, monkeypatch)
    try:
        state = await public.state(operator, match_id)
        command_id, request_id = uuid4(), uuid4()
        running = CommandResult(
            command_id=command_id,
            request_id=request_id,
            match_id=match_id,
            status=CommandStatus.RUNNING,
            accepted_revision=1,
        )
        completed = running.model_copy(
            update={"status": CommandStatus.COMPLETED, "resulting_revision": 2}
        )
        first = SnapshotEvent(match_id=match_id, event_id="run:1", payload=state, resync=False)
        resync = first.model_copy(update={"event_id": "new:1", "resync": True})
        streams, cursors = [], []
        status_calls = 0

        def handler(request):
            nonlocal status_calls
            if "/commands/" in request.url.path:
                status_calls += 1
                return httpx.Response(
                    200, json=(completed if status_calls >= 3 else running).model_dump(mode="json")
                )
            cursors.append(request.headers.get("last-event-id"))
            event = first if len(cursors) == 1 else resync
            encoded = frame(event)
            stream = Chunks([b": heartbeat\n\n", encoded[:13], encoded[13:]])
            streams.append(stream)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        async with AsyncAW2Client(transport=httpx.MockTransport(handler), retry_delay=0.001) as sdk:
            result = await sdk.wait_for_command(match_id, command_id, timeout=2)
            assert result.status is CommandStatus.COMPLETED
            assert cursors == [None, "run:1"]
            assert all(s.closed for s in streams)
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_sdk_wait_timeout_releases_stream_without_cancelling_server_work():
    match_id, command_id = uuid4(), uuid4()
    stream = Chunks([], hang=True)
    running = CommandResult(
        command_id=command_id,
        request_id=uuid4(),
        match_id=match_id,
        status=CommandStatus.RUNNING,
        accepted_revision=1,
    )
    requests = []

    def handler(request):
        requests.append(request.method)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        return httpx.Response(200, json=running.model_dump(mode="json"))

    async with AsyncAW2Client(transport=httpx.MockTransport(handler)) as sdk:
        with pytest.raises(WaitTimeout) as caught:
            await sdk.wait_for_command(match_id, command_id, timeout=0.05)
        assert caught.value.command_id == command_id
        assert stream.closed
        assert requests == ["GET", "GET"]


@run_async_test
async def test_sdk_protocol_and_transport_errors_do_not_expose_secrets():
    identifier = uuid4()

    def fail(request):
        raise httpx.ConnectError("private-token-or-path")

    async with AsyncAW2Client(transport=httpx.MockTransport(fail), retries=0) as sdk:
        with pytest.raises(TransportError) as caught:
            await sdk.create_match(request_id=identifier)
        assert caught.value.request_id == identifier
        assert "private" not in str(caught.value)
    async with AsyncAW2Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"garbage": "secret"}))
    ) as sdk:
        with pytest.raises(ProtocolError) as caught:
            await sdk.capabilities()
        assert "secret" not in str(caught.value)


@run_async_test
async def test_sdk_lifecycle_separate_players_and_invitation_secret_serialization(
    tmp_path, monkeypatch
):
    from aw2_lab.authorization import AuthorizationService
    from aw2_lab.match_contract import PlayerSlot
    from aw2_lab.match_controller import MatchController

    controller = MatchController(
        authorization=AuthorizationService(tmp_path / "auth.json", token("o"))
    )
    await controller.start()
    app = application(controller, tmp_path, monkeypatch)
    try:
        async with (
            AsyncAW2Client(credential=token("o"), transport=httpx.ASGITransport(app=app)) as admin,
            AsyncAW2Client(credential=token("p"), transport=httpx.ASGITransport(app=app)) as red,
            AsyncAW2Client(credential=token("q"), transport=httpx.ASGITransport(app=app)) as blue,
        ):
            match = await admin.create_match()
            for slot, invitation, client in (
                (PlayerSlot.SLOT_1, token("i"), red),
                (PlayerSlot.SLOT_2, token("j"), blue),
            ):
                await admin.invite(match.match_id, slot, invitation)
                joined = await client.join(match.match_id, slot, invitation, slot.value)
                assert joined.player_slot is slot
            assert (await blue.inspect_match(match.match_id)).slots[0].status.value == "joined"
            await admin.revoke(match.match_id, PlayerSlot.SLOT_1)
            with pytest.raises(APIError) as revoked:
                await red.state(match.match_id)
            assert revoked.value.status == 401
            closed = await admin.close(match.match_id)
            await controller.wait_for_command(match.match_id, closed.command_id, timeout=2)
            assert (
                await admin.wait_for_command(match.match_id, closed.command_id)
            ).status is CommandStatus.COMPLETED
    finally:
        await controller.stop()


@run_async_test
async def test_sdk_turn_subscription_cleanup_and_rejects_mismatched_framing(
    memory, tmp_path, monkeypatch
):
    _app, runtime, public, match_id, operator, _ = await setup(memory, tmp_path, monkeypatch)
    try:
        state = await public.state(operator, match_id)
        event = SnapshotEvent(match_id=match_id, event_id="run:1", payload=state, resync=True)
        stream = Chunks([frame(event)], hang=True)

        def handler(request):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        async with AsyncAW2Client(transport=httpx.MockTransport(handler)) as sdk:
            turn = await sdk.wait_for_turn(match_id, PlayerSlot.SLOT_1, timeout=2)
            assert turn.summary.revision == 1
            assert stream.closed
        bad = frame(event).replace(b"id: run:1", b"id: wrong")
        async with AsyncAW2Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=Chunks([bad])
                )
            )
        ) as sdk:
            events = sdk.events(match_id)
            try:
                with pytest.raises(ProtocolError):
                    await anext(events)
            finally:
                await events.aclose()
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_checkpoint_export_stops_at_archive_limit():
    from aw2_lab.checkpoint_store import MAX_ARCHIVE_BYTES

    class ArchiveStream(httpx.AsyncByteStream):
        def __init__(self):
            self.chunks = 0
            self.closed = False

        async def __aiter__(self):
            for _ in range(100):
                self.chunks += 1
                yield b"x" * 65536

        async def aclose(self):
            self.closed = True

    stream = ArchiveStream()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    async with AsyncAW2Client(transport=transport) as client:
        with pytest.raises(ProtocolError, match="exceeds limit"):
            await client.export_checkpoint(uuid4(), uuid4())
    assert stream.closed
    assert stream.chunks <= MAX_ARCHIVE_BYTES // 65536 + 2


@run_async_test
async def test_screenshot_metadata_is_bound_to_requested_boundary():
    match_id, revision = uuid4(), 4
    png = b"\x89PNG\r\n\x1a\nfixture"

    def transport(response_match, response_revision, frame):
        return httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=png,
                headers={
                    "content-type": "image/png",
                    "X-AW2-Match-ID": str(response_match),
                    "X-AW2-Revision": str(response_revision),
                    "X-AW2-Frame": str(frame),
                },
            )
        )

    async with AsyncAW2Client(transport=transport(match_id, revision, 123)) as client:
        result = await client.screenshot(match_id, revision=revision)
        assert (result.match_id, result.revision, result.frame, result.png) == (
            match_id,
            revision,
            123,
            png,
        )
    async with AsyncAW2Client(transport=transport(match_id, revision + 1, 123)) as client:
        with pytest.raises(ProtocolError, match="requested boundary"):
            await client.screenshot(match_id, revision=revision)
    async with AsyncAW2Client(transport=transport(uuid4(), revision, 123)) as client:
        with pytest.raises(ProtocolError, match="requested boundary"):
            await client.screenshot(match_id, revision=revision)
