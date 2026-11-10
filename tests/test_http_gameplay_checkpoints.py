"""Public gameplay/checkpoint routes through the real queue and synthetic runtime."""

import io
from uuid import UUID, uuid4
from zipfile import ZIP_STORED, ZipFile

import pytest
from test_authorization import token
from test_http_api import application, client_for, headers
from test_match_controller import run_async_test
from test_playable_runtime import setup as runtime_setup
from test_state_validation import memory as memory  # noqa: PLC0414

import aw2_lab.playable_runtime as runtime_module
from aw2_lab.authorization import AuthorizationService
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.checkpoint_store import MAX_ARCHIVE_BYTES
from aw2_lab.match_contract import CommandStatus, MatchLifecycle, PlayerSlot
from aw2_lab.match_controller import MatchController, MutationOutcome


async def setup(memory, tmp_path, monkeypatch):
    runtime, public, match_id, operator, bridge = await runtime_setup(memory, tmp_path)
    app = application(runtime.controller, tmp_path, monkeypatch)
    runtime._session_changed = lambda service: setattr(
        app.state, "match_checkpoint_service", service
    )
    async with client_for(app) as client:
        started = await client.post(
            f"/v1/matches/{match_id}/start",
            headers=headers(),
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
            },
        )
        assert started.status_code == 202, started.text
        result = await runtime.controller.wait_for_command(
            match_id, UUID(started.json()["command_id"]), timeout=2
        )
        assert result.status is CommandStatus.COMPLETED
    return app, runtime, public, match_id, operator, bridge


async def finished(client, runtime, match_id, response):
    assert response.status_code == 202, response.text
    command_id = UUID(response.json()["command_id"])
    await runtime.controller.wait_for_command(match_id, command_id, timeout=2)
    result = await client.get(f"/v1/matches/{match_id}/commands/{command_id}", headers=headers("p"))
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize(
    "kind,executor_name,extra",
    [
        ("move_wait", "MoveWaitActionExecutor", {"unit_id": "1", "path": []}),
        (
            "move_attack",
            "MoveAttackActionExecutor",
            {"unit_id": "1", "path": [], "target": {"x": 1, "y": 1}},
        ),
        ("attack", "MoveAttackActionExecutor", {"unit_id": "1", "target": {"x": 1, "y": 1}}),
        ("move_capture", "MoveCaptureActionExecutor", {"unit_id": "1", "path": []}),
        (
            "purchase",
            "PurchaseActionExecutor",
            {"property": {"x": 1, "y": 1}, "unit_type": "Infantry"},
        ),
        ("activate_super_power", "ActivateSuperPowerActionExecutor", {}),
        ("end_turn", "EndTurnActionExecutor", {}),
        ("surrender", "SurrenderActionExecutor", {}),
    ],
)
@run_async_test
async def test_typed_http_gameplay_dispatch_retry_and_sse(
    memory, tmp_path, monkeypatch, kind, executor_name, extra
):
    app, runtime, _public, match_id, operator, bridge = await setup(memory, tmp_path, monkeypatch)
    calls = []

    class Executor:
        def __init__(self, navigator, tracker, *_runtime_args):
            self.tracker = tracker

        async def execute(self, request, observation):
            calls.append(request.action.kind)
            bridge.frame += 1
            return MutationOutcome(
                observation=self.tracker.commit_boundary(await bridge.decoded()),
                lifecycle=MatchLifecycle.PLAYABLE,
            )

    monkeypatch.setattr(runtime_module, executor_name, Executor)
    subscription = await app.state.authorized_matches.subscribe_events(operator, match_id)
    await subscription.next()
    try:
        async with client_for(app) as client:
            body = {
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "action": {"kind": kind, **extra},
            }
            denied = await client.post(
                f"/v1/matches/{match_id}/commands", json=body, headers=headers()
            )
            assert denied.status_code == 403
            submitted = await client.post(
                f"/v1/matches/{match_id}/commands", json=body, headers=headers("p")
            )
            result = await finished(client, runtime, match_id, submitted)
            assert result["status"] == "completed" and result["resulting_revision"] == 2, (
                result.get("error")
            )
            assert calls == [kind]
            retry = await client.post(
                f"/v1/matches/{match_id}/commands", json=body, headers=headers("p")
            )
            assert retry.json()["command_id"] == submitted.json()["command_id"]
            assert calls == [kind]
            events = [(await subscription.next(timeout=1)).event for _ in range(5)]
            assert events[-2].event == "match.updated" and events[-2].payload.summary.revision == 2
            assert (
                events[-1].event == "command.updated"
                and events[-1].payload.status is CommandStatus.COMPLETED
            )
            stale = await client.post(
                f"/v1/matches/{match_id}/commands",
                json=dict(body, request_id=str(uuid4())),
                headers=headers("p"),
            )
            assert (await finished(client, runtime, match_id, stale))["error"][
                "code"
            ] == "stale_revision"
            wrong_turn = await client.post(
                f"/v1/matches/{match_id}/commands",
                json=dict(body, request_id=str(uuid4()), expected_revision=2),
                headers=headers("q"),
            )
            assert (await finished(client, runtime, match_id, wrong_turn))["error"][
                "code"
            ] == "not_your_turn"
    finally:
        subscription.close()
        await runtime.controller.stop()


@run_async_test
async def test_http_checkpoint_create_reads_import_restore_and_revocation(
    memory, tmp_path, monkeypatch
):
    app, runtime, public, match_id, operator, bridge = await setup(memory, tmp_path, monkeypatch)
    base = f"/v1/matches/{match_id}"
    try:
        async with client_for(app) as client:
            caps = (await client.get("/v1/capabilities")).json()
            actions = {item["name"]: item for item in caps["actions"]}
            assert all(item["available"] for item in actions.values())
            assert "activate_normal_power" in actions
            assert "activate_super_power" in actions
            assert "unload" in {item["name"] for item in caps["actions"]}
            assert next(item for item in caps["operations"] if item["name"] == "checkpoints")[
                "available"
            ]
            body = {"request_id": str(uuid4()), "expected_revision": 1}
            saved = await client.post(base + "/checkpoints", json=body, headers=headers("q"))
            result = await finished(client, runtime, match_id, saved)
            assert result["status"] == "completed" and result["resulting_revision"] == 1
            checkpoint_id = result["checkpoint_id"]
            assert (
                await client.post(base + "/checkpoints", json=body, headers=headers("q"))
            ).json()["command_id"] == saved.json()["command_id"]
            path = base + f"/checkpoints/{checkpoint_id}"
            listed = await client.get(base + "/checkpoints", headers=headers("p"))
            assert checkpoint_id in [ref["checkpoint_id"] for ref in listed.json()["checkpoints"]]
            inspected = await client.get(path, headers=headers("p"))
            assert (
                inspected.status_code == 200
                and inspected.json()["compatibility"]["emulator_build"] == "synthetic-mgba"
            )
            assert "credential" not in inspected.text and str(tmp_path) not in inspected.text
            assert (
                await client.get(base + f"/checkpoints/{uuid4()}", headers=headers("p"))
            ).status_code == 404
            assert (await client.get(path + "/archive", headers=headers("p"))).status_code == 403
            archive = await client.get(path + "/archive", headers=headers())
            assert (
                archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
            )
            assert (
                archive.headers["content-disposition"]
                == f'attachment; filename="{checkpoint_id}.zip"'
            )
            assert archive.headers["cache-control"] == "no-store"
            before = (runtime.store.current(), bridge.frame, bridge.loads)
            import_id = str(uuid4())
            upload_headers = {
                **headers(),
                "Content-Type": "application/zip",
                "Request-ID": import_id,
            }
            imported = await client.post(
                base + "/checkpoints/import", content=archive.content, headers=upload_headers
            )
            assert imported.status_code == 201, imported.text
            assert imported.json()["checkpoint_id"] == checkpoint_id
            assert (
                await client.post(
                    base + "/checkpoints/import", content=archive.content, headers=upload_headers
                )
            ).json() == imported.json()
            conflict = await client.post(
                base + "/checkpoints/import",
                content=archive.content + b"changed",
                headers=upload_headers,
            )
            assert (
                conflict.status_code == 409
                and conflict.json()["error"]["code"] == "request_id_conflict"
            )
            assert (runtime.store.current(), bridge.frame, bridge.loads) == before
            assert (
                await client.post(
                    path + "/restore",
                    json=dict(body, request_id=str(uuid4())),
                    headers=headers("p"),
                )
            ).status_code == 403
            await public.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
            restored = await client.post(
                path + "/restore", json=dict(body, request_id=str(uuid4())), headers=headers()
            )
            receipt_id = UUID(restored.json()["command_id"])
            done = await runtime.controller.wait_for_command(match_id, receipt_id, timeout=2)
            assert done.status is CommandStatus.COMPLETED and done.resulting_revision == 2
            assert done.checkpoint_id != UUID(checkpoint_id)
            assert (await client.get(path, headers=headers("p"))).status_code == 401
            state = (await client.get(base + "/state", headers=headers("q"))).json()
            assert state["summary"]["slots"][0]["status"] == "revoked"
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_archive_bounds_validation_and_request_namespace(memory, tmp_path, monkeypatch):
    app, runtime, _public, match_id, _operator, bridge = await setup(memory, tmp_path, monkeypatch)
    base = f"/v1/matches/{match_id}"
    try:
        async with client_for(app) as client:
            before = (runtime.store.current(), bridge.loads, bridge.frame)
            upload = {**headers(), "Content-Type": "application/zip", "Request-ID": str(uuid4())}
            for data, status in (
                (b"broken", 400),
                (b"", 400),
                (b"x" * (MAX_ARCHIVE_BYTES + 1), 413),
            ):
                response = await client.post(
                    base + "/checkpoints/import", content=data, headers=upload
                )
                assert response.status_code == status, response.text
                assert response.json()["request_id"] == upload["Request-ID"]
            assert (
                await client.post(
                    base + "/checkpoints/import",
                    content=b"x",
                    headers={**upload, "Content-Type": "application/json"},
                )
            ).status_code == 415
            assert (
                await client.post(
                    base + "/checkpoints/import",
                    content=b"x",
                    headers={**upload, "Request-ID": "invalid"},
                )
            ).status_code == 422
            assert (
                await client.post(
                    base + "/checkpoints/import",
                    content=b"x",
                    headers={
                        **headers("p"),
                        "Content-Type": "application/zip",
                        "Request-ID": str(uuid4()),
                    },
                )
            ).status_code == 403
            assert (runtime.store.current(), bridge.loads, bridge.frame) == before
            # Failed imports do not reserve a request ID; successful ones conflict
            # with command and setup operations using that same ID.
            archive = await client.get(
                base + f"/checkpoints/{runtime.store.current().checkpoint_id}/archive",
                headers=headers(),
            )
            imported = await client.post(
                base + "/checkpoints/import", content=archive.content, headers=upload
            )
            assert imported.status_code == 201, imported.text
            conflict = await client.post(
                base + "/checkpoints",
                json={"request_id": upload["Request-ID"], "expected_revision": 1},
                headers=headers("p"),
            )
            assert conflict.status_code == 409
            same_metadata = await client.post(
                "/v1/matches", json={"request_id": upload["Request-ID"]}, headers=headers()
            )
            assert same_metadata.status_code == 409
            created = await client.post(
                base + "/checkpoints",
                json={"request_id": str(uuid4()), "expected_revision": 1},
                headers=headers("p"),
            )
            command_collision = await client.post(
                base + "/checkpoints/import",
                content=archive.content,
                headers={**upload, "Request-ID": created.json()["request_id"]},
            )
            assert command_collision.status_code == 409
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_import_receipt_survives_operator_restart(memory, tmp_path, monkeypatch):
    app, runtime, _public, match_id, _operator, _bridge = await setup(memory, tmp_path, monkeypatch)
    base = f"/v1/matches/{match_id}"
    upload = {**headers(), "Content-Type": "application/zip", "Request-ID": str(uuid4())}
    try:
        async with client_for(app) as client:
            pointer = runtime.store.current()
            archive = (
                await client.get(
                    base + f"/checkpoints/{pointer.checkpoint_id}/archive", headers=headers()
                )
            ).content
            original = await client.post(
                base + "/checkpoints/import", content=archive, headers=upload
            )
            assert original.status_code == 201
        boundary = await runtime.controller.current_state(match_id)
    finally:
        await runtime.controller.stop()
    controller = MatchController(
        authorization=AuthorizationService(tmp_path / "auth.json", token("o"))
    )
    await controller.adopt_recovered_match(boundary.summary, boundary.observation, {})
    restored_app = application(controller, tmp_path, monkeypatch)
    # A durable import receipt and archive reads require no initialized session
    # or live compatibility identity after restart.
    restored_app.state.authorized_matches = AuthorizedMatchService(
        controller, checkpoint_store=runtime.store
    )
    try:
        async with client_for(restored_app) as client:
            retried = await client.post(
                base + "/checkpoints/import", content=archive, headers=upload
            )
            assert retried.status_code == 201, retried.text
            assert retried.json() == original.json()
            assert runtime.store.current() == pointer
            assert (
                await client.get(base + "/checkpoints", headers=headers("q"))
            ).status_code == 200
            assert (
                await client.get(
                    base + f"/checkpoints/{pointer.checkpoint_id}/archive", headers=headers()
                )
            ).content == archive
            new_import = await client.post(
                base + "/checkpoints/import",
                content=archive,
                headers={**upload, "Request-ID": str(uuid4())},
            )
            assert new_import.status_code == 503
            restored_app.state.authorized_matches = AuthorizedMatchService(
                controller,
                checkpoint_store=runtime.store,
                checkpoint_identity_provider=lambda: runtime.identity,
            )
            fresh = await client.post(
                base + "/checkpoints/import",
                content=archive,
                headers={**upload, "Request-ID": str(uuid4())},
            )
            assert fresh.status_code == 201
    finally:
        await controller.stop()


@run_async_test
async def test_foreign_incompatible_and_corrupt_checkpoints_are_rejected(
    memory, tmp_path, monkeypatch
):
    app, runtime, _public, match_id, _operator, bridge = await setup(memory, tmp_path, monkeypatch)
    base = f"/v1/matches/{match_id}"
    try:
        pointer = runtime.store.current()
        manifest, state = runtime.store.load(pointer.checkpoint_id)
        foreign = manifest.model_copy(
            update={
                "checkpoint_id": uuid4(),
                "match": manifest.match.model_copy(update={"match_id": uuid4()}),
            }
        )
        runtime.store.save(foreign, state)
        incompatible = manifest.model_copy(
            update={"checkpoint_id": uuid4(), "emulator_build": "other-build"}
        )
        before = (runtime.store.current(), bridge.loads, bridge.frame)
        async with client_for(app) as client:
            listed = await client.get(base + "/checkpoints", headers=headers("q"))
            assert str(foreign.checkpoint_id) not in listed.text
            assert (
                await client.get(base + f"/checkpoints/{foreign.checkpoint_id}", headers=headers())
            ).status_code == 404
            for artifact in (foreign, incompatible):
                output = io.BytesIO()
                with ZipFile(output, "w", compression=ZIP_STORED) as archive:
                    archive.writestr("manifest.json", artifact.model_dump_json())
                    archive.writestr("state.bin", state)
                rejected = await client.post(
                    base + "/checkpoints/import",
                    content=output.getvalue(),
                    headers={
                        **headers(),
                        "Content-Type": "application/zip",
                        "Request-ID": str(uuid4()),
                    },
                )
                assert rejected.status_code == 409, rejected.text
                assert rejected.json()["error"]["code"] == "checkpoint_incompatible"
            assert (runtime.store.current(), bridge.loads, bridge.frame) == before
            path = runtime.store.root / str(manifest.checkpoint_id) / "state.bin"
            path.write_bytes(b"corrupted")
            corrupted = await client.get(
                base + f"/checkpoints/{manifest.checkpoint_id}", headers=headers("q")
            )
            assert corrupted.status_code == 400
            assert corrupted.json()["error"]["code"] == "checkpoint_corrupt"
            assert str(tmp_path) not in corrupted.text
    finally:
        await runtime.controller.stop()


@run_async_test
async def test_restore_http_recovers_failed_action_and_publishes_sse(memory, tmp_path, monkeypatch):
    app, runtime, _public, match_id, operator, _bridge = await setup(memory, tmp_path, monkeypatch)
    base = f"/v1/matches/{match_id}"
    checkpoint_id = runtime.store.current().checkpoint_id

    class FailingExecutor:
        def __init__(self, *_args):
            pass

        async def execute(self, *_args):
            raise RuntimeError("synthetic executor failed")

    async def failed_rollback(*_args):
        raise RuntimeError("synthetic rollback failed")

    monkeypatch.setattr(runtime_module, "EndTurnActionExecutor", FailingExecutor)
    runtime.controller.set_recovery_rollback_provider(failed_rollback, replace=True)
    subscription = await app.state.authorized_matches.subscribe_events(operator, match_id)
    await subscription.next()
    try:
        async with client_for(app) as client:
            action = await client.post(
                base + "/commands",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "action": {"kind": "end_turn"},
                },
                headers=headers("p"),
            )
            failed = await finished(client, runtime, match_id, action)
            assert failed["status"] == "recovery_required"
            restore_body = {
                "request_id": str(uuid4()),
                "expected_revision": failed["resulting_revision"],
            }
            restored = await client.post(
                base + f"/checkpoints/{checkpoint_id}/restore", json=restore_body, headers=headers()
            )
            outcome = await finished(client, runtime, match_id, restored)
            assert (
                outcome["status"] == "completed"
                and outcome["resulting_revision"] > failed["resulting_revision"]
            )
            seen = []
            while True:
                current = (await subscription.next(timeout=1)).event
                seen.append(current)
                if (
                    current.event == "command.updated"
                    and str(current.payload.command_id) == outcome["command_id"]
                    and current.payload.status is CommandStatus.COMPLETED
                ):
                    break
            assert seen[-2].event == "match.updated"
            assert seen[-2].payload.summary.lifecycle is MatchLifecycle.PLAYABLE
            assert seen[-2].payload.summary.revision == outcome["resulting_revision"]
    finally:
        subscription.close()
        await runtime.controller.stop()
