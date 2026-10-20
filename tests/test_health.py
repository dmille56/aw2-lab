from fastapi.testclient import TestClient

from aw2_lab.api.app import app


def test_health_reports_http_and_emulator_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "emulator": "not_started"}
