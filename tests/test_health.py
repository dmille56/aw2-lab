from pathlib import Path

import httpx
import pytest

from aw2_lab.api.app import app, create_app


@pytest.mark.anyio
async def test_health_reports_http_and_emulator_status() -> None:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "emulator": "not_started"}


def test_app_keeps_optional_rom_path() -> None:
    assert app.state.rom_path is None

    rom_path = create_app(rom_path=Path("/tmp/aw2.gba"))

    assert rom_path.state.rom_path == Path("/tmp/aw2.gba")
