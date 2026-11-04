"""ROM-independent checks for the prototype server's ROM configuration."""

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from fastapi import FastAPI
from test_match_controller import run_async_test


@pytest.fixture
def prototype() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "prototypes" / "client" / "serve.py"
    spec = importlib.util.spec_from_file_location("client_prototype_serve", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("use_cli", [False, True])
def test_rom_path_configuration(
    prototype: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, use_cli: bool
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(b"ROM contents are not inspected in this configuration test")
    monkeypatch.setenv("AW2_ROM_PATH", "missing.gba" if use_cli else str(rom))
    monkeypatch.setattr(
        "sys.argv", ["serve.py", "--rom-path", str(rom)] if use_cli else ["serve.py"]
    )
    app = FastAPI()
    observed = {}

    def create_app(*, settings):
        observed["settings"] = settings
        return app

    def run(application, **kwargs):
        observed["application"] = application
        observed["options"] = kwargs

    monkeypatch.setattr(prototype, "create_app", create_app)
    monkeypatch.setattr(prototype.uvicorn, "run", run)
    prototype.main()

    assert observed["settings"].rom_path == rom.resolve()
    assert observed["application"] is app
    assert observed["options"] == {"host": "127.0.0.1", "port": 43127}


@pytest.mark.parametrize("env_value", [None, "", "missing.gba", "."])
def test_invalid_rom_configuration_reports_parser_error(
    prototype: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    env_value: str | None,
) -> None:
    if env_value is None:
        monkeypatch.delenv("AW2_ROM_PATH", raising=False)
    else:
        monkeypatch.setenv("AW2_ROM_PATH", env_value)
    monkeypatch.setattr("sys.argv", ["serve.py"])

    with pytest.raises(SystemExit) as exc:
        prototype.main()

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert ("provide --rom-path or set AW2_ROM_PATH" if not env_value else "not a file") in error


def test_authenticated_windowed_configuration(prototype, monkeypatch, tmp_path):
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(b"ROM configuration test")
    secret = tmp_path / "operator-token"
    storage = tmp_path / "storage"
    observed = {}

    def create_app(**kwargs):
        observed.update(kwargs)
        return FastAPI()

    monkeypatch.setattr(prototype, "create_app", create_app)
    monkeypatch.setattr(prototype.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "serve.py",
            "--rom-path",
            str(rom),
            "--operator-secret-file",
            str(secret),
            "--storage-dir",
            str(storage),
            "--emulator-mode",
            "windowed",
        ],
    )
    prototype.main()
    assert observed["settings"].mode.value == "windowed"
    assert observed["operator_secret_file"] == secret
    assert observed["storage_root"] == storage


@run_async_test
async def test_viewer_assets_and_native_authorization_preflight(prototype):
    app = FastAPI()
    prototype.configure_client(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/client/")).status_code == 200
        for asset in ("client.js", "style.css", "health.js", "transport.js", "catalog.json"):
            assert (await client.get(f"/client/{asset}")).status_code == 200
        catalog = (await client.get("/client/catalog.json")).json()
        assert catalog["schema_version"] == 1
        assert catalog["units"]["1"]["name"] == "Infantry"
        for origin in ("tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"):
            response = await client.options(
                "/v1/matches/example/state",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
            assert "authorization" in response.headers["access-control-allow-headers"].lower()
        denied = await client.options(
            "/health",
            headers={"Origin": "https://unrelated.example", "Access-Control-Request-Method": "GET"},
        )
        assert denied.status_code == 400
        assert "access-control-allow-origin" not in denied.headers


def test_bundled_catalog_is_generated_from_shared_rules():
    path = Path(__file__).resolve().parents[1] / "prototypes/client/generate_catalog.py"
    spec = importlib.util.spec_from_file_location("client_catalog_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CATALOG_PATH.read_text() == module.catalog_text()
