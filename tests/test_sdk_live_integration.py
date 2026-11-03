"""Opt-in SDK acceptance against real CLI servers, TCP/SSE, and both mGBA frontends."""

import asyncio
import hashlib
import io
import json
import os
import socket
import sys
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.match_contract import (
    CommandStatus,
    Coordinate,
    EndTurnAction,
    MoveAttackAction,
    MoveCaptureAction,
    MoveWaitAction,
    PlayerSlot,
    PurchaseAction,
    SurrenderAction,
)
from aw2_lab.sdk import AsyncAW2Client, WaitTimeout
from aw2_lab.state_decoder import capture_game_state

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_SDK_LIVE_TESTS") != "1",
    reason="set AW2_RUN_SDK_LIVE_TESTS=1 and AW2_ROM_PATH for listening-server acceptance",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def coords(points):
    return tuple(Coordinate(x=x, y=y) for x, y in points)


@asynccontextmanager
async def server(root, mode, rom):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = (root / "server.log").open("ab")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "aw2_lab",
        "--rom",
        str(rom),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--emulator-mode",
        mode,
        "--storage-dir",
        str(root / "storage"),
        "--operator-secret-file",
        str(root / "operator-token"),
        "--enable-debug-api",
        stdout=log,
        stderr=log,
    )
    try:
        async with httpx.AsyncClient() as health:
            async with asyncio.timeout(40):
                while True:
                    assert process.returncode is None, (
                        f"Server exited; inspect {root / 'server.log'}"
                    )
                    try:
                        if (await health.get(url + "/health")).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.05)
        yield url
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 40)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        finally:
            log.close()


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_two_sdk_clients_play_save_restart_and_finish(mode, tmp_path):
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check():
        operator = SecretStr(token_urlsafe(32))
        players = [SecretStr(token_urlsafe(32)), SecretStr(token_urlsafe(32))]
        token_file = tmp_path / "operator-token"
        token_file.write_text(operator.get_secret_value())
        token_file.chmod(0o600)
        evidence = {
            "mode": mode,
            "rom_sha256": sha(rom.read_bytes()),
            "commands": [],
            "boundaries": [],
        }
        source_save = rom.with_suffix(".sav")
        source_save_hash = sha(source_save.read_bytes()) if source_save.is_file() else None
        match_id = None

        async def record(client, label):
            state = await client.state(match_id)
            assert state.settled
            battle = state.observation.game_state.battle.value
            if label in {"neutral-partial", "neutral-complete", "hq-partial"}:
                position = (14, 7) if label == "hq-partial" else (5, 4)
                prop = next(p for p in battle.properties if (p.x, p.y) == position)
                infantry_unit = next(
                    u for u in battle.units if u.army_slot == 1 and u.unit_type == 1
                )
                assert (
                    prop.owner_slot
                    == {"neutral-partial": 0, "neutral-complete": 1, "hq-partial": 2}[label]
                )
                assert infantry_unit.capture_points == (0 if label == "neutral-complete" else 10)
            if label == "midgame":
                attacker = next(u for u in battle.units if u.army_slot == 1 and u.unit_type == 5)
                target = next(u for u in battle.units if u.army_slot == 2 and u.unit_type == 5)
                assert (attacker.x, attacker.y) == (7, 5) and attacker.used_this_turn
                assert target.internal_health < 100 and attacker.ammo == 8
            if label == "hq-victory":
                assert battle is None
                assert state.observation.game_state.lifecycle.phase.value == "victory_presentation"
            evidence["boundaries"].append(
                {
                    "label": label,
                    "revision": state.summary.revision,
                    "lifecycle": state.summary.lifecycle.value,
                    "frame": state.observation.game_state.frame,
                    "state_sha256": sha(
                        json.dumps(state.observation.game_state.to_dict(), sort_keys=True).encode()
                    ),
                }
            )
            (tmp_path / f"{label}.json").write_text(state.model_dump_json(indent=2))
            return state

        async def action(
            client,
            label,
            command,
            *,
            expected="completed",
            request_id=None,
            revision=None,
            expire_wait=False,
        ):
            state = await client.state(match_id)
            receipt = await client.submit(
                match_id,
                state.summary.revision if revision is None else revision,
                command,
                request_id=request_id,
            )
            if expire_wait:
                with pytest.raises(WaitTimeout):
                    await client.wait_for_command(match_id, receipt.command_id, timeout=0.005)
                evidence["client_wait_timeout_did_not_cancel"] = True
            result = await client.wait_for_command(match_id, receipt.command_id, timeout=120)
            evidence["commands"].append({"label": label, **result.model_dump(mode="json")})
            print(mode, label, result.status.value, flush=True)
            assert result.status.value == expected, result.error
            return result

        def unit_id(state, kind, army=1):
            battle = state.observation.game_state.battle.value
            unit = next(u for u in battle.units if u.army_slot == army and u.unit_type == kind)
            return next(
                i.identity_id
                for i in state.observation.unit_identities
                if i.reference == unit.reference
            )

        async def round_end(red, blue):
            await action(red, "red-end", EndTurnAction())
            await blue.wait_for_turn(match_id, PlayerSlot.SLOT_2, timeout=30)
            await action(blue, "blue-end", EndTurnAction())
            await red.wait_for_turn(match_id, PlayerSlot.SLOT_1, timeout=30)

        try:
            async with (
                server(tmp_path, mode, rom) as url,
                AsyncAW2Client(url, credential=operator) as admin,
                AsyncAW2Client(url, credential=players[0]) as red,
                AsyncAW2Client(url, credential=players[1]) as blue,
            ):
                match = await admin.create_match()
                match_id = match.match_id
                for slot, client in zip(PlayerSlot, (red, blue), strict=True):
                    invitation = SecretStr(token_urlsafe(32))
                    await admin.invite(match_id, slot, invitation)
                    await client.join(match_id, slot, invitation, slot.value)
                receipt = await admin.start(match_id, 0)
                start = await admin.wait_for_command(match_id, receipt.command_id, timeout=200)
                assert start.status is CommandStatus.COMPLETED, start.error
                initial = await record(red, "initial")
                assert initial.observation.game_state.battle.value.active_player_slot == 1
                initial_archive = await admin.export_checkpoint(match_id, start.checkpoint_id)
                with zipfile.ZipFile(io.BytesIO(initial_archive)) as archive:
                    native = archive.read("state.bin")
                    (tmp_path / "initial.state").write_bytes(native)
                    manifest = json.loads(archive.read("manifest.json"))
                evidence["initial_native_sha256"] = sha(native)
                evidence["emulator_build"] = manifest["emulator_build"]
                evidence["save_ram_included"] = manifest.get(
                    "state_artifact", manifest.get("artifact")
                )
                purchase_id = uuid4()
                bought = await action(
                    red,
                    "purchase-infantry",
                    PurchaseAction(property=Coordinate(x=3, y=6), unit_type="Infantry"),
                    request_id=purchase_id,
                )
                retry = await red.submit(
                    match_id,
                    1,
                    PurchaseAction(property=Coordinate(x=3, y=6), unit_type="Infantry"),
                    request_id=purchase_id,
                )
                assert retry.command_id == bought.command_id
                await action(red, "stale-request", EndTurnAction(), revision=1, expected="rejected")
                await action(blue, "wrong-turn", EndTurnAction(), expected="rejected")
                await action(
                    red,
                    "purchase-tank",
                    PurchaseAction(property=Coordinate(x=1, y=6), unit_type="Tank"),
                    expire_wait=True,
                )
                state = await red.state(match_id)
                infantry, tank = unit_id(state, 1), unit_id(state, 5)
                await action(red, "red-end-day1", EndTurnAction())
                await action(
                    blue,
                    "purchase-blue-tank",
                    PurchaseAction(property=Coordinate(x=12, y=6), unit_type="Tank"),
                )
                await action(blue, "blue-end-day1", EndTurnAction())
                await action(
                    red,
                    "illegal-route",
                    MoveWaitAction(unit_id=infantry, path=coords([(0, 0)])),
                    expected="rejected",
                )
                await action(
                    red,
                    "infantry-approach",
                    MoveWaitAction(unit_id=infantry, path=coords([(3, 5), (4, 5)])),
                )
                await action(
                    red,
                    "tank-south",
                    MoveWaitAction(
                        unit_id=tank,
                        path=coords([(1, 7), (1, 8), (1, 9), (2, 9), (3, 9), (4, 9)]),
                    ),
                )
                await action(red, "red-end-day2", EndTurnAction())
                blue_tank = unit_id(await blue.state(match_id), 5, 2)
                await action(
                    blue,
                    "blue-tank-south",
                    MoveWaitAction(
                        unit_id=blue_tank,
                        path=coords([(12, 7), (12, 8), (12, 9), (11, 9), (10, 9)]),
                    ),
                )
                await action(blue, "blue-end-day2", EndTurnAction())
                await action(
                    red,
                    "neutral-partial",
                    MoveCaptureAction(unit_id=infantry, path=coords([(5, 5), (5, 4)])),
                )
                await record(red, "neutral-partial")
                await action(
                    red,
                    "tank-north",
                    MoveWaitAction(
                        unit_id=tank,
                        path=coords([(5, 9), (5, 8), (5, 7), (5, 6), (5, 5), (6, 5)]),
                    ),
                )
                await action(red, "red-end-day3", EndTurnAction())
                await action(
                    blue,
                    "blue-tank-north",
                    MoveWaitAction(
                        unit_id=blue_tank,
                        path=coords([(10, 8), (10, 7), (10, 6), (10, 5), (9, 5), (8, 5)]),
                    ),
                )
                await action(blue, "blue-end-day3", EndTurnAction())
                await action(red, "neutral-complete", MoveCaptureAction(unit_id=infantry, path=()))
                await record(red, "neutral-complete")
                await action(
                    red,
                    "move-attack",
                    MoveAttackAction(
                        unit_id=tank, path=coords([(7, 5)]), target=Coordinate(x=8, y=5)
                    ),
                )
                mid = await record(red, "midgame")
                receipt = await red.create_checkpoint(match_id, mid.summary.revision)
                saved = await red.wait_for_command(match_id, receipt.command_id, timeout=60)
                assert saved.status is CommandStatus.COMPLETED
                checkpoint = saved.checkpoint_id
                archive = await admin.export_checkpoint(match_id, checkpoint)
                (tmp_path / "midgame.zip").write_bytes(archive)
                imported = await admin.import_checkpoint(match_id, archive)
                assert imported.checkpoint_id == checkpoint
                await action(red, "surrender", SurrenderAction())
                terminal = await record(blue, "surrender-finished")
                assert terminal.summary.lifecycle.value == "finished"
                receipt = await admin.restore_checkpoint(
                    match_id, checkpoint, terminal.summary.revision
                )
                assert (
                    await admin.wait_for_command(match_id, receipt.command_id, timeout=60)
                ).status is CommandStatus.COMPLETED
                restored = await record(red, "restored")
                assert restored.observation.game_state == mid.observation.game_state
                assert restored.observation.unit_identities == mid.observation.unit_identities
                assert restored.summary.revision > mid.summary.revision
                # Leave the active match open; clean process shutdown/restart must resume it.
            async with (
                server(tmp_path, mode, rom) as url,
                AsyncAW2Client(url, credential=operator) as admin,
                AsyncAW2Client(url, credential=players[0]) as red,
                AsyncAW2Client(url, credential=players[1]) as blue,
            ):
                resumed = await record(red, "resumed")
                assert resumed.summary.revision > restored.summary.revision
                assert resumed.observation.game_state == restored.observation.game_state
                assert resumed.observation.unit_identities == restored.observation.unit_identities
                retry = await red.submit(
                    match_id,
                    1,
                    PurchaseAction(property=Coordinate(x=3, y=6), unit_type="Infantry"),
                    request_id=purchase_id,
                )
                assert retry.command_id == bought.command_id
                await round_end(red, blue)
                for label, path in [
                    ("hq-route1", [(6, 4), (7, 4), (8, 4)]),
                    ("hq-route2", [(9, 4), (10, 4), (10, 5)]),
                    ("hq-route3", [(11, 5), (12, 5)]),
                    ("hq-route4", [(13, 5), (14, 5), (14, 6)]),
                ]:
                    await action(red, label, MoveWaitAction(unit_id=infantry, path=coords(path)))
                    await round_end(red, blue)
                await action(
                    red,
                    "hq-partial",
                    MoveCaptureAction(unit_id=infantry, path=coords([(14, 7)])),
                )
                await record(red, "hq-partial")
                await round_end(red, blue)
                await action(red, "hq-victory", MoveCaptureAction(unit_id=infantry, path=()))
                victory = await record(blue, "hq-victory")
                assert victory.summary.lifecycle.value == "finished"
                png = await blue.screenshot(match_id, revision=victory.summary.revision)
                (tmp_path / "victory.png").write_bytes(png)
                evidence["victory_png_sha256"] = sha(png)
                if source_save_hash is not None:
                    assert sha(source_save.read_bytes()) == source_save_hash
                evidence["source_save_unchanged_sha256"] = source_save_hash
                evidence["passed"] = True
        finally:
            (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(check())


def test_identical_native_checkpoint_and_inputs_match_between_frontends(tmp_path):
    source = Path(os.environ.get("AW2_SDK_PARITY_STATE_PATH", ""))
    if not source.is_file():
        pytest.skip(
            "set AW2_SDK_PARITY_STATE_PATH to the fixed-match initial.state from the SDK run"
        )
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("frontend parity requires a display")
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file()
    native = source.read_bytes()

    async def check():
        observations = []
        evidence = {"native_sha256": sha(native), "rom_sha256": sha(rom.read_bytes()), "runs": []}
        sequence = [(16, 1), (0, 30), (32, 1), (0, 30)]
        for mode in EmulatorMode:
            launcher = EmulatorLauncher(
                EmulatorSettings(rom_path=rom, mode=mode, suppress_emulator_output=True),
                isolate_saves=True,
            )
            try:
                await launcher.start()
                bridge = launcher.bridge
                await bridge.load_state_buffer(native)
                before = await capture_game_state(bridge, rom_path=rom)
                for keys, frames in sequence:
                    await bridge.press_keys(keys, frames)
                after = await capture_game_state(bridge, rom_path=rom)
                document = {"before": before.to_dict(), "after": after.to_dict()}
                encoded = json.dumps(document, sort_keys=True).encode()
                observations.append(document)
                (tmp_path / f"{mode.value}.json").write_bytes(encoded)
                evidence["runs"].append(
                    {
                        "mode": mode.value,
                        "build": launcher.build_identity,
                        "observations_sha256": sha(encoded),
                        "inputs": sequence,
                    }
                )
            finally:
                await launcher.stop()
        assert observations[0] == observations[1]
        evidence["passed"] = True
        (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_input_timeout_rollback_and_explicit_recovery(mode, tmp_path, monkeypatch):

    import uvicorn

    from aw2_lab.api import app as app_module

    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file()
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")

    async def check():
        token = SecretStr(token_urlsafe(32))
        player = SecretStr(token_urlsafe(32))
        secret = tmp_path / "operator-token"
        secret.write_text(token.get_secret_value())
        secret.chmod(0o600)
        app = app_module.create_app(
            settings=EmulatorSettings(
                rom_path=rom, mode=EmulatorMode(mode), suppress_emulator_output=True
            ),
            storage_root=tmp_path / "storage",
            operator_secret_file=secret,
        )
        async with app.router.lifespan_context(app):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            sock.setblocking(False)
            url = f"http://127.0.0.1:{sock.getsockname()[1]}"
            http = uvicorn.Server(
                uvicorn.Config(app, lifespan="off", log_level="error", timeout_graceful_shutdown=2)
            )
            task = asyncio.create_task(http.serve(sockets=[sock]))
            try:
                async with asyncio.timeout(10):
                    while not http.started:
                        await asyncio.sleep(0.01)
                async with (
                    AsyncAW2Client(url, credential=token) as admin,
                    AsyncAW2Client(url, credential=player) as red,
                ):
                    match = await admin.create_match()
                    for slot in PlayerSlot:
                        invite = SecretStr(token_urlsafe(32))
                        cred = player if slot is PlayerSlot.SLOT_1 else SecretStr(token_urlsafe(32))
                        await admin.invite(match.match_id, slot, invite)
                        async with AsyncAW2Client(url, credential=cred) as client:
                            await client.join(match.match_id, slot, invite, slot.value)
                    receipt = await admin.start(match.match_id, 0)
                    started = await admin.wait_for_command(
                        match.match_id, receipt.command_id, timeout=200
                    )
                    assert started.status is CommandStatus.COMPLETED, started.error
                    before = await red.state(match.match_id)
                    runtime = app.state.playable_runtime
                    bridge = runtime.bridge
                    press = bridge.press_keys
                    applied = []

                    async def fail_after_input(keys, frames):
                        applied.append((keys, frames))
                        await press(keys, frames)
                        raise TimeoutError("Injected timeout after confirmed real controller input")

                    monkeypatch.setattr(bridge, "press_keys", fail_after_input)
                    purchase = PurchaseAction(property=Coordinate(x=1, y=6), unit_type="Infantry")
                    receipt = await red.submit(match.match_id, before.summary.revision, purchase)
                    rolled = await red.wait_for_command(
                        match.match_id, receipt.command_id, timeout=120
                    )
                    assert rolled.status is CommandStatus.ROLLED_BACK, rolled.error
                    after = await red.state(match.match_id)
                    assert applied
                    assert after.observation.game_state == before.observation.game_state
                    assert after.observation.unit_identities == before.observation.unit_identities
                    assert after.summary.revision > before.summary.revision

                    async def fail_restore(*args):
                        raise RuntimeError("Injected rollback provider failure")

                    runtime.controller.set_recovery_rollback_provider(fail_restore, replace=True)
                    receipt = await red.submit(match.match_id, after.summary.revision, purchase)
                    failed = await red.wait_for_command(
                        match.match_id, receipt.command_id, timeout=120
                    )
                    assert failed.status is CommandStatus.RECOVERY_REQUIRED
                    assert (
                        await red.state(match.match_id)
                    ).summary.lifecycle.value == "recovery_required"
                    monkeypatch.setattr(bridge, "press_keys", press)
                    receipt = await admin.restore_checkpoint(
                        match.match_id, started.checkpoint_id, failed.resulting_revision
                    )
                    restored = await admin.wait_for_command(
                        match.match_id, receipt.command_id, timeout=120
                    )
                    assert restored.status is CommandStatus.COMPLETED, restored.error
                    receipt = await red.submit(
                        match.match_id, restored.resulting_revision, purchase
                    )
                    continued = await red.wait_for_command(
                        match.match_id, receipt.command_id, timeout=120
                    )
                    assert continued.status is CommandStatus.COMPLETED, continued.error
                    evidence = {
                        "mode": mode,
                        "rom_sha256": sha(rom.read_bytes()),
                        "build": app.state.emulator_launcher.build_identity,
                        "injection": "TimeoutError after confirmed press_keys; failed rollback provider on second action",
                        "actual_inputs": applied,
                        "results": [
                            r.model_dump(mode="json") for r in (rolled, failed, restored, continued)
                        ],
                        "passed": True,
                    }
                    (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2))
            finally:
                http.should_exit = True
                await task
                sock.close()

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["headless", "windowed"])
def test_live_debug_operations_restore_ready_boundary(mode, tmp_path):
    import base64

    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file()
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed debug checks require a display")

    async def check():
        operator = SecretStr(token_urlsafe(32))
        player = SecretStr(token_urlsafe(32))
        secret = tmp_path / "operator-token"
        secret.write_text(operator.get_secret_value())
        secret.chmod(0o600)
        async with (
            server(tmp_path, mode, rom) as url,
            AsyncAW2Client(url, credential=operator) as admin,
            httpx.AsyncClient(
                base_url=url, headers={"Authorization": f"Bearer {operator.get_secret_value()}"}
            ) as raw,
        ):
            match = await admin.create_match()
            for slot in PlayerSlot:
                invite = SecretStr(token_urlsafe(32))
                cred = player if slot is PlayerSlot.SLOT_1 else SecretStr(token_urlsafe(32))
                await admin.invite(match.match_id, slot, invite)
                async with AsyncAW2Client(url, credential=cred) as client:
                    await client.join(match.match_id, slot, invite, slot.value)
            receipt = await admin.start(match.match_id, 0)
            started = await admin.wait_for_command(match.match_id, receipt.command_id, timeout=200)
            assert started.status is CommandStatus.COMPLETED, started.error
            base = f"/v1/matches/{match.match_id}/debug"

            async def read(revision, *, credential=None):
                response = await raw.post(
                    base + "/memory/read",
                    json={"expected_revision": revision, "address": 0x0203FFF0, "length": 1},
                    headers={"Authorization": f"Bearer {credential.get_secret_value()}"}
                    if credential
                    else None,
                )
                return response

            denied = await read(1, credential=player)
            assert denied.status_code == 403
            before = await read(1)
            assert before.status_code == 200, before.text
            original = base64.b64decode(before.json()["data"])
            altered = base64.b64encode(bytes([original[0] ^ 1])).decode()
            evidence = {"mode": mode, "rom_sha256": sha(rom.read_bytes()), "results": []}
            for operation, extra in [
                ("frames", {"frames": 1}),
                ("buttons", {"buttons": ["select"], "frames": 1}),
                ("memory/write", {"address": 0x0203FFF0, "data": altered}),
                ("reset", {}),
            ]:
                state = await admin.state(match.match_id)
                response = await raw.post(
                    base + "/" + operation,
                    json={
                        "request_id": str(uuid4()),
                        "expected_revision": state.summary.revision,
                        **extra,
                    },
                )
                assert response.status_code == 202, response.text
                from uuid import UUID

                result = await admin.wait_for_command(
                    match.match_id, UUID(response.json()["command_id"]), timeout=120
                )
                assert result.status is CommandStatus.RECOVERY_REQUIRED, result.error
                invalidated = await admin.state(match.match_id)
                assert invalidated.observation.identity_status.value == "unavailable"
                assert invalidated.summary.revision > state.summary.revision
                restore = await admin.restore_checkpoint(
                    match.match_id, started.checkpoint_id, invalidated.summary.revision
                )
                restored = await admin.wait_for_command(
                    match.match_id, restore.command_id, timeout=120
                )
                assert restored.status is CommandStatus.COMPLETED, restored.error
                after = await read(restored.resulting_revision)
                assert after.status_code == 200, after.text
                assert base64.b64decode(after.json()["data"]) == original
                evidence["results"].append(
                    {
                        "operation": operation,
                        "mutation": result.model_dump(mode="json"),
                        "restore": restored.model_dump(mode="json"),
                    }
                )
            evidence["passed"] = True
            (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2))

    asyncio.run(check())
