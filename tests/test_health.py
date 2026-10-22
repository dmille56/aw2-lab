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
