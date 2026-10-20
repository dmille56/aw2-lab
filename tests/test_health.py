from pathlib import Path

from fastapi.testclient import TestClient

from aw2_lab.api.app import app, create_app


def test_health_reports_http_and_emulator_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "emulator": "not_started"}


def test_app_keeps_optional_rom_path() -> None:
    assert app.state.rom_path is None

    rom_path = create_app(rom_path=Path("/tmp/aw2.gba"))

    assert rom_path.state.rom_path == Path("/tmp/aw2.gba")
