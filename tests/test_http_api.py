"""Public HTTP authorization, lifecycle, redaction, and coherent cached-image behavior."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from test_authorization import token
from test_authorized_match import prepare
from test_health import FakeLauncher
from test_match_controller import IncrementingExecutor, run_async_test
from test_playable_runtime import setup as runtime_setup
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab.api import app as app_module
from aw2_lab.api_contract import GameplayCommandRequest
from aw2_lab.authorization import AuthorizationService
from aw2_lab.emulator import EmulatorSettings
from aw2_lab.match_contract import CommandStatus, PlayerSlot
from aw2_lab.match_controller import MatchController
from aw2_lab.rom_profile import AW2_US_REVISION_0


def headers(letter="o"):
    return {"Authorization": f"Bearer {letter * 43}"}


def application(controller, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    return app_module.create_app(
        settings=EmulatorSettings(rom_path=tmp_path / "rom.gba"),
        launcher=FakeLauncher(),
        match_controller=controller,
        storage_root=tmp_path / "application",
    )


def client_for(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://aw2.test",
    )


@run_async_test
async def test_creation_uses_advertised_profile_and_rejects_other_configurations(
    tmp_path, monkeypatch
):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    app = application(controller, tmp_path, monkeypatch)
    async with client_for(app) as client:
        caps = (await client.get("/v1/capabilities")).json()
        advertised = next(
            profile["configuration"]
            for profile in caps["configuration_profiles"]
            if profile["profile_id"] == caps["default_profile_id"]
        )
        options = caps["configuration_options"]
        assert options["combination_constraint"] == "verified_profiles_only"
        assert advertised["map_id"] in options["map_ids"]
        assert advertised["players"] == options["players"]
        assert advertised["rules"] == options["rules"]
        assert advertised["rules"]["weather"] == "clear"
        assert advertised["rules"]["day_limit"] == 30
        assert advertised["rules"]["capture_limit"] is None
        assert len(options["co_ids"]) == 19
        assert "starting_weather" not in advertised["rules"]
        assert len(advertised["players"]) in caps["supported_player_counts"]
        for player in advertised["players"]:
            assert player["co_id"] in options["co_ids"]
            assert player["control"] in caps["supported_control_modes"]

        alternatives = []
        for field, value in (
            ("fog", True),
            ("weather", "rain"),
            ("weather", "snow"),
            ("weather", "random"),
            ("income_per_property", 2000),
            ("day_limit", None),
            ("day_limit", 5),
            ("day_limit", 20),
            ("day_limit", 99),
            ("co_powers", False),
        ):
            changed = deepcopy(advertised)
            changed["rules"][field] = value
            alternatives.append((changed, "unsupported_feature"))
        for field, value in (
            ("color", "green"),
            ("team_id", "b"),
            ("control", "computer"),
            ("co_id", "unknown_co"),
            ("slot", "slot_2"),
        ):
            changed = deepcopy(advertised)
            changed["players"][0][field] = value
            code = (
                "invalid_request"
                if field == "slot" or value == "unknown_co"
                else "unsupported_feature"
            )
            alternatives.append((changed, code))
        for count in (3, 4):
            changed = deepcopy(advertised)
            for index, color in enumerate(("green", "yellow")[: count - 2], start=3):
                changed["players"].append(
                    dict(changed["players"][0], slot=f"slot_{index}", color=color)
                )
            alternatives.append((changed, "unsupported_feature"))
        changed = deepcopy(advertised)
        changed["map_id"] = "unknown_map"
        alternatives.append((changed, "invalid_request"))
        changed = deepcopy(advertised)
        changed["players"][1]["color"] = changed["players"][0]["color"]
        alternatives.append((changed, "invalid_request"))
        for day_limit in (0, 1, 2, 3, 4, 100, True, False, "30", 30.0):
            changed = deepcopy(advertised)
            changed["rules"]["day_limit"] = day_limit
            alternatives.append((changed, "invalid_request"))
        for capture_limit in (12, 20, 27, 0, 11, 28, True, False, "12", 12.0):
            changed = deepcopy(advertised)
            changed["rules"]["capture_limit"] = capture_limit
            code = (
                "unsupported_feature"
                if type(capture_limit) is int and 12 <= capture_limit <= 27
                else "invalid_request"
            )
            alternatives.append((changed, code))
        changed = deepcopy(advertised)
        del changed["rules"]["capture_limit"]
        alternatives.append((changed, "invalid_request"))
        for weather in ("storm", "Random", None, True, 0):
            changed = deepcopy(advertised)
            changed["rules"]["weather"] = weather
            alternatives.append((changed, "invalid_request"))
        changed = deepcopy(advertised)
        changed["rules"]["starting_weather"] = changed["rules"].pop("weather")
        alternatives.append((changed, "invalid_request"))

        request_id = str(uuid4())
        for configuration, code in alternatives:
            rejected = await client.post(
                "/v1/matches",
                json={"request_id": request_id, "configuration": configuration},
                headers=headers(),
            )
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["error"]["code"] == code
            assert rejected.json()["request_id"] == request_id
            assert (await client.get("/v1/matches", headers=headers())).json()["matches"] == []

        # Rejections must not reserve the request ID. CO selections are supported
        # and remain durable across retries and metadata recovery.
        selected = deepcopy(advertised)
        selected["players"][0]["co_id"] = "sami"
        selected["players"][1]["co_id"] = "nell"
        body = {"request_id": request_id, "configuration": selected}
        created = await client.post("/v1/matches", json=body, headers=headers())
        assert created.status_code == 201, created.text
        assert created.json()["configuration"] == selected
        assert (
            await client.post("/v1/matches", json=body, headers=headers())
        ).json() == created.json()

    restored = MatchController(
        authorization=AuthorizationService(tmp_path / "auth.json", token("o"))
    )
    await restored.recover_authorized_setup()
    restored_app = application(restored, tmp_path, monkeypatch)
    async with client_for(restored_app) as client:
        inspected = await client.get(f"/v1/matches/{created.json()['match_id']}", headers=headers())
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["configuration"] == selected


@run_async_test
async def test_http_setup_join_retry_close_and_revocation(tmp_path, monkeypatch):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    await controller.start()
    app = application(controller, tmp_path, monkeypatch)
    try:
        async with client_for(app) as client:
            request = {"request_id": str(uuid4())}
            rejected = await client.post("/v1/matches", json=request)
            assert rejected.status_code == 401
            assert rejected.headers["www-authenticate"] == "Bearer"
            created = await client.post("/v1/matches", json=request, headers=headers())
            assert created.status_code == 201, created.text
            match = created.json()["match_id"]
            base = f"/v1/matches/{match}"
            assert created.headers["location"] == base
            retry = await client.post("/v1/matches", json=request, headers=headers())
            assert retry.json() == created.json()
            assert (await client.get("/v1/matches", headers=headers())).json()["matches"] == [
                created.json()
            ]
            state = await client.get(base + "/state", headers=headers())
            assert state.json()["settled"] is True and state.json()["observation"] is None
            assert (await client.get(base + "/observation", headers=headers())).status_code == 409
            assert (await client.get(base + "/screenshot", headers=headers())).status_code == 409

            invitation = {"request_id": str(uuid4()), "invitation_token": "i" * 43}
            invited = await client.post(
                base + "/slots/slot_1/invitations", json=invitation, headers=headers()
            )
            assert invited.status_code == 201 and "i" * 43 not in invited.text
            join_body = {
                "request_id": str(uuid4()),
                "display_name": "Red",
                "invitation_token": "i" * 43,
            }
            joined = await client.post(
                base + "/slots/slot_1/join", json=join_body, headers=headers("p")
            )
            assert joined.status_code == 200, joined.text
            assert "p" * 43 not in joined.text
            assert (
                await client.post(base + "/slots/slot_1/join", json=join_body, headers=headers("p"))
            ).json() == joined.json()
            assert (await client.get(base, headers=headers("p"))).status_code == 200
            assert (await client.get("/v1/matches", headers=headers("p"))).status_code == 403
            assert (
                await client.post(
                    "/v1/matches", json={"request_id": str(uuid4())}, headers=headers("p")
                )
            ).status_code == 403
            start = await client.post(
                base + "/start",
                json={"request_id": str(uuid4()), "expected_revision": 0},
                headers=headers(),
            )
            assert start.status_code == 503
            denied_close = await client.post(
                base + "/close", json={"request_id": str(uuid4())}, headers=headers("p")
            )
            assert denied_close.status_code == 403
            close_body = {"request_id": str(uuid4())}
            closed = await client.post(base + "/close", json=close_body, headers=headers())
            assert closed.status_code == 202
            command_id = UUID(closed.json()["command_id"])
            await controller.wait_for_command(UUID(match), command_id, timeout=1)
            result = await client.get(base + f"/commands/{command_id}", headers=headers("p"))
            assert result.json()["status"] == "completed"
            assert (await client.get(base, headers=headers("p"))).json()["lifecycle"] == "closed"
            assert (await client.post(base + "/close", json=close_body, headers=headers())).json()[
                "command_id"
            ] == str(command_id)
            assert (
                await client.get(base + f"/commands/{uuid4()}", headers=headers())
            ).status_code == 404
            assert (
                await client.get(f"/v1/matches/{uuid4()}", headers=headers("p"))
            ).status_code == 403
            revoked = await client.post(
                base + "/slots/slot_1/revoke", json={"request_id": str(uuid4())}, headers=headers()
            )
            assert revoked.status_code == 200
            assert (await client.get(base, headers=headers("p"))).status_code == 401
            assert state.headers["cache-control"] == "no-store"
    finally:
        await controller.stop()


@pytest.mark.parametrize(
    ("body", "content_type", "status"),
    [
        ("{", "application/json", 400),
        ("{}", "text/plain", 415),
        ("x" * 65537, "application/json", 413),
        ("[]", "application/json", 422),
    ],
)
@run_async_test
async def test_http_bounds_and_safe_errors(tmp_path, monkeypatch, body, content_type, status):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    app = application(controller, tmp_path, monkeypatch)
    async with client_for(app) as client:
        response = await client.post(
            "/v1/matches", content=body, headers={**headers(), "Content-Type": content_type}
        )
        assert response.status_code == status, response.text
        assert response.json()["error"]["code"] == "invalid_request"
        assert response.headers["cache-control"] == "no-store"


@run_async_test
async def test_http_redacts_validation_and_unexpected_errors(tmp_path, monkeypatch):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    app = application(controller, tmp_path, monkeypatch)
    request_id = str(uuid4())
    async with client_for(app) as client:
        response = await client.post(
            f"/v1/matches/{uuid4()}/slots/slot_1/invitations",
            headers=headers(),
            json={
                "request_id": request_id,
                "invitation_token": "sensitive",
                "secret-extra": "private",
            },
        )
        assert response.status_code == 422
        assert response.json()["request_id"] == request_id
        assert all(value not in response.text for value in ("sensitive", "private", "secret-extra"))

        async def fail(*args):
            raise RuntimeError("private /local/server/path " + "o" * 43)

        monkeypatch.setattr(app.state.authorized_matches, "inspect", fail)
        failed = await client.get(f"/v1/matches/{uuid4()}", headers=headers())
        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "internal_error"
        assert "private" not in failed.text and "o" * 43 not in failed.text
        assert (await client.get("/v1/unknown")).status_code == 404
        assert (await client.delete("/v1/matches")).status_code == 405


@run_async_test
async def test_capabilities_are_public_and_match_access_requires_provisioning(
    tmp_path, monkeypatch
):
    app = application(MatchController(), tmp_path, monkeypatch)
    async with client_for(app) as client:
        caps = await client.get("/v1/capabilities")
        assert caps.status_code == 200
        document = caps.json()
        assert [item["terrain_class"] for item in document["production_facilities"]] == [
            14,
            11,
            10,
        ]
        assert document["production_facilities"][1]["unit_types"] == [
            "Battleship",
            "Cruiser",
            "Lander",
            "Submarine",
        ]
        assert document["production_facilities"][2]["unit_types"] == [
            "Fighter",
            "Bomber",
            "Battle Copter",
            "Transport Copter",
        ]
        assert document["supported_game_contract_versions"] == [1]
        assert document["supported_match_observation_schema_versions"] == [1]
        assert document["supported_game_state_schema_versions"] == [5]
        assert document["supported_control_modes"] == ["external"]
        assert document["http_sse"]["implemented"] is True
        assert document["http_sse"]["available"] is False
        assert not any(
            feature["available"] for feature in document["operations"] + document["actions"]
        )
        assert (await client.get("/v1/matches", headers=headers())).status_code == 503
        schema = (await client.get("/openapi.json")).json()
        assert "HTTPBearer" in schema["components"]["securitySchemes"]


@run_async_test
async def test_readiness_is_operator_only_and_does_not_claim_playable_match(tmp_path, monkeypatch):
    auth = AuthorizationService(tmp_path / "auth.json", token("o"))
    controller = MatchController(authorization=auth)
    app = application(controller, tmp_path, monkeypatch)
    async with client_for(app) as client:
        denied = await client.get("/v1/readiness")
        response = await client.get("/v1/readiness", headers=headers())
        assert denied.status_code == 401
        assert response.status_code == 200, response.text
        assert response.json() == {
            "contract_version": 1,
            "http": "ready",
            "emulator": "unavailable",
            "bridge": "not_configured",
            "queue": "unavailable",
            "recovery": "not_required",
            "match_id": None,
            "match_lifecycle": None,
            "match_ready": False,
        }


@run_async_test
async def test_http_start_queues_the_shared_runtime(memory, tmp_path, monkeypatch):
    runtime, public, match_id, _, _ = await runtime_setup(memory, tmp_path)
    app = application(public.controller, tmp_path, monkeypatch)
    try:
        async with client_for(app) as client:
            caps = (await client.get("/v1/capabilities")).json()
            assert next(item for item in caps["operations"] if item["name"] == "start_match")[
                "available"
            ]
            body = {"request_id": str(uuid4()), "expected_revision": 0}
            started = await client.post(
                f"/v1/matches/{match_id}/start", json=body, headers=headers()
            )
            assert started.status_code == 202, started.text
            result = await public.controller.wait_for_command(
                match_id, UUID(started.json()["command_id"]), timeout=2
            )
            assert result.status is CommandStatus.COMPLETED
            assert runtime.store.current().command_result == result
            state = await client.get(f"/v1/matches/{match_id}/state", headers=headers("q"))
            assert state.json()["summary"]["revision"] == 1 and state.json()["settled"]
    finally:
        await public.controller.stop()


@run_async_test
async def test_screenshot_reads_are_cached_coherent_and_revocation_checked(
    memory, tmp_path, monkeypatch
):
    class ControlledExecutor(IncrementingExecutor):
        def __init__(self, *args):
            super().__init__(*args)
            self.block = False
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def execute(self, request, observation):
            if self.block:
                self.entered.set()
                await self.release.wait()
            return await super().execute(request, observation)

    public, match_id, op, player, _, executor = await prepare(
        memory, tmp_path, factory=ControlledExecutor
    )
    captures = []

    async def capture(observation):
        captures.append(observation.revision)
        return b"\x89PNG\r\n\x1a\n" + str(observation.game_state.frame).encode()

    public.controller.set_screenshot_provider(capture)
    app = application(public.controller, tmp_path, monkeypatch)
    base = f"/v1/matches/{match_id}"

    async def submit(revision):
        return await public.submit(
            player,
            match_id,
            GameplayCommandRequest(
                request_id=uuid4(), expected_revision=revision, action={"kind": "end_turn"}
            ),
        )

    try:
        first = await submit(1)
        await public.wait_for_command(op, match_id, first.command_id, timeout=1)
        async with client_for(app) as client:
            image = await client.get(base + "/screenshot?revision=2", headers=headers("q"))
            assert image.status_code == 200 and image.headers["content-type"] == "image/png"
            assert image.headers["x-aw2-revision"] == "2" and image.headers[
                "x-aw2-match-id"
            ] == str(match_id)
            frame = image.headers["x-aw2-frame"]
            executor.block = True
            pending = await submit(2)
            await asyncio.wait_for(executor.entered.wait(), 1)
            state = await client.get(base + "/state", headers=headers("q"))
            assert state.json()["settled"] is False and state.json()["observation"]["revision"] == 2
            assert (
                await client.get(base + "/observation", headers=headers("q"))
            ).status_code == 409
            cached = await client.get(base + "/screenshot", headers=headers("q"))
            assert cached.content == image.content and cached.headers["x-aw2-frame"] == frame
            assert captures == [2]
            executor.release.set()
            await public.wait_for_command(op, match_id, pending.command_id, timeout=1)
            assert (
                await client.get(base + "/screenshot?revision=2", headers=headers("q"))
            ).status_code == 409
            assert (
                await client.get(base + "/screenshot?revision=3", headers=headers("q"))
            ).status_code == 200

            async def broken(observation):
                raise OSError("private screenshot failure")

            public.controller.set_screenshot_provider(broken)
            pending = await submit(3)
            result = await public.wait_for_command(op, match_id, pending.command_id, timeout=1)
            assert result.status is CommandStatus.COMPLETED
            assert (await client.get(base + "/screenshot", headers=headers("q"))).status_code == 409
            await public.revoke(op, match_id, PlayerSlot.SLOT_2, uuid4())
            assert (await client.get(base + "/screenshot", headers=headers("q"))).status_code == 401
    finally:
        executor.release.set()
        await public.controller.stop()


@run_async_test
async def test_restored_and_closed_matches_keep_correct_cached_screenshot(
    memory, tmp_path, monkeypatch
):
    public, match_id, op, _, _, _ = await prepare(memory, tmp_path)
    snapshot = await public.controller.current_state(match_id)
    hashes = await public.controller.credential_hashes(match_id)
    await public.controller.stop()

    async def capture(observation):
        return b"\x89PNG\r\n\x1a\nrestored"

    recovered = MatchController(authorization=public.authorization, screenshot_provider=capture)
    await recovered.adopt_recovered_match(snapshot.summary, snapshot.observation, hashes)
    await recovered.cache_restored_screenshot(match_id)
    await recovered.start()
    app = application(recovered, tmp_path, monkeypatch)
    try:
        async with client_for(app) as client:
            base = f"/v1/matches/{match_id}"
            image = await client.get(base + "/screenshot", headers=headers("p"))
            assert image.status_code == 200
            assert image.headers["x-aw2-revision"] == str(snapshot.summary.revision)
            receipt = await app.state.authorized_matches.close(op, match_id, uuid4())
            await recovered.wait_for_command(match_id, receipt.command_id, timeout=1)
            closed_image = await client.get(base + "/screenshot", headers=headers("p"))
            assert closed_image.content == image.content
            assert closed_image.headers["x-aw2-revision"] == image.headers["x-aw2-revision"]
    finally:
        await recovered.stop()


@pytest.mark.parametrize("frames", [(123, 123), (124,), (123, 124)])
@run_async_test
async def test_runtime_never_labels_a_different_frame_as_boundary_screenshot(
    memory, tmp_path, frames
):
    runtime, public, match_id, op, _ = await runtime_setup(memory, tmp_path)
    try:
        from aw2_lab.api_contract import StartMatchRequest

        receipt = await public.start(
            op, match_id, StartMatchRequest(request_id=uuid4(), expected_revision=0)
        )
        await public.wait_for_command(op, match_id, receipt.command_id, timeout=2)
        observation = await public.observation(op, match_id)
        remaining = iter(frames)

        async def read(ranges):
            return SimpleNamespace(frame=next(remaining))

        async def screenshot():
            return b"\x89PNG\r\n\x1a\nframe123"

        # Exercise the production capture method with a frame-changing transport.
        bridge = SimpleNamespace(read_memory_snapshot=read, screenshot=screenshot)
        runtime.bridge = bridge
        if frames == (123, 123):
            assert (await runtime.capture_screenshot(observation)).endswith(b"frame123")
        else:
            with pytest.raises(RuntimeError, match="frame|advanced"):
                await runtime.capture_screenshot(observation)
    finally:
        await public.controller.stop()


@run_async_test
async def test_match_identity_is_authenticated_scoped_and_revoked(memory, tmp_path, monkeypatch):
    service, match_id, operator, _, _, _ = await prepare(memory, tmp_path)
    app = application(service.controller, tmp_path, monkeypatch)
    url = f"/v1/matches/{match_id}/identity"
    try:
        async with client_for(app) as client:
            for letter, role, slot in (
                ("o", "operator", None),
                ("p", "player", "slot_1"),
                ("q", "player", "slot_2"),
            ):
                response = await client.get(url, headers=headers(letter))
                assert response.status_code == 200, response.text
                assert response.json() == {
                    "contract_version": 1,
                    "match_id": str(match_id),
                    "role": role,
                    "player_slot": slot,
                }
                assert "no-store" in response.headers["cache-control"]
            assert (await client.get(url)).status_code == 401
            assert (
                await client.get(f"/v1/matches/{uuid4()}/identity", headers=headers("p"))
            ).status_code == 403
            await service.revoke(operator, match_id, PlayerSlot.SLOT_1, uuid4())
            assert (await client.get(url, headers=headers("p"))).status_code == 401
    finally:
        await service.controller.stop()
