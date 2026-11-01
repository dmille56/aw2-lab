from pathlib import Path

import httpx
import pytest

from aw2_lab.api import app as api_app
from aw2_lab.api.app import create_app
from aw2_lab.emulator import EmulatorMode, EmulatorSettings
from aw2_lab.rom_profile import AW2_US_REVISION_0, UnsupportedRomError


class FakeLauncher:
    def __init__(self) -> None:
        self.is_running = False
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True
        self.is_running = True

    async def stop(self) -> None:
        self.stopped = True
        self.is_running = False


@pytest.mark.anyio
async def test_health_reports_emulator_process_status_and_lifespan_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_app, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    launcher = FakeLauncher()
    application = create_app(
        settings=EmulatorSettings(rom_path=tmp_path / "aw2.gba"), launcher=launcher
    )
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/health")

    assert launcher.started
    assert launcher.stopped
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "emulator": "running"}


def test_app_stores_emulator_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_app, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    rom_path = tmp_path / "aw2.gba"
    settings = EmulatorSettings(rom_path=rom_path, mode=EmulatorMode.WINDOWED)
    application = create_app(settings=settings)

    assert application.state.emulator_settings is settings
    assert application.state.rom_profile is AW2_US_REVISION_0


def test_app_rejects_unsupported_rom_before_emulator_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = FakeLauncher()

    def reject_rom(_: Path) -> None:
        raise UnsupportedRomError("unsupported image")

    monkeypatch.setattr(api_app, "select_rom_profile", reject_rom)

    with pytest.raises(UnsupportedRomError, match="unsupported image"):
        create_app(settings=EmulatorSettings(rom_path=tmp_path / "bad.gba"), launcher=launcher)

    assert not launcher.started


@pytest.mark.anyio
async def test_operator_file_wires_authorized_setup_recovery(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from pydantic import SecretStr

    from aw2_lab.api_contract import CreateMatchRequest
    from aw2_lab.authorization import AuthorizationError

    monkeypatch.setattr(api_app, "select_rom_profile", lambda _: AW2_US_REVISION_0)

    @asynccontextmanager
    async def session_manager():
        yield

    monkeypatch.setattr(
        api_app, "mcp_server", SimpleNamespace(session_manager=SimpleNamespace(run=session_manager))
    )
    secret = tmp_path / "operator-secret"
    secret.write_text("o" * 43 + "\n")
    secret.chmod(0o600)
    root = tmp_path / "storage"
    settings = EmulatorSettings(rom_path=tmp_path / "aw2.gba")
    application = create_app(
        settings=settings, launcher=FakeLauncher(), storage_root=root, operator_secret_file=secret
    )
    async with application.router.lifespan_context(application):
        service = application.state.authorized_matches
        principal = service.authenticate(SecretStr("o" * 43))
        summary = await service.create(principal, CreateMatchRequest(request_id=uuid4()))
    # Omitting the operator file must not enable legacy checkpoint authorization.
    with pytest.raises(AuthorizationError):
        create_app(settings=settings, storage_root=root)
    restarted = create_app(
        settings=settings, launcher=FakeLauncher(), storage_root=root, operator_secret_file=secret
    )
    async with restarted.router.lifespan_context(restarted):
        service = restarted.state.authorized_matches
        principal = service.authenticate(SecretStr("o" * 43))
        assert (await service.inspect(principal, summary.match_id)).lifecycle.value == "setup"


@pytest.mark.anyio
async def test_application_wires_runtime_to_its_launcher_bridge(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    monkeypatch.setattr(api_app, "select_rom_profile", lambda _: AW2_US_REVISION_0)

    @asynccontextmanager
    async def sessions():
        yield

    monkeypatch.setattr(
        api_app, "mcp_server", SimpleNamespace(session_manager=SimpleNamespace(run=sessions))
    )
    launcher = FakeLauncher()
    launcher.bridge = SimpleNamespace()
    launcher.build_identity = "synthetic-mgba"
    secret = tmp_path / "operator-secret"
    secret.write_text("o" * 43)
    secret.chmod(0o600)
    application = create_app(
        settings=EmulatorSettings(rom_path=tmp_path / "rom.gba"),
        launcher=launcher,
        storage_root=tmp_path / "data",
        operator_secret_file=secret,
    )
    async with application.router.lifespan_context(application):
        runtime = application.state.playable_runtime
        assert runtime.bridge is launcher.bridge
        assert runtime.controller is application.state.match_controller
        assert runtime.store is application.state.checkpoint_store
        assert application.state.authorized_matches.controller is runtime.controller
