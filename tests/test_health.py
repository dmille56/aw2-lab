from pathlib import Path

import httpx
import pytest

from aw2_lab.api.app import create_app
from aw2_lab.emulator import EmulatorMode, EmulatorSettings


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
    tmp_path: Path,
) -> None:
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


def test_app_stores_emulator_configuration(tmp_path: Path) -> None:
    rom_path = tmp_path / "aw2.gba"
    settings = EmulatorSettings(rom_path=rom_path, mode=EmulatorMode.WINDOWED)
    application = create_app(settings=settings)

    assert application.state.emulator_settings is settings
