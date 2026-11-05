"""ROM-independent checks for the prototype server's ROM configuration."""

import importlib.util
import json
import tomllib
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from fastapi import FastAPI
from test_match_controller import run_async_test

from aw2_lab.api_contract import CapabilitiesResponse, StateResponse


@pytest.fixture
def prototype(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setenv("AW2_CLIENT_DIST", str(tmp_path))
    path = Path(__file__).resolve().parents[1] / "prototypes" / "client" / "serve.py"
    spec = importlib.util.spec_from_file_location("client_prototype_serve", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_smoke_reserves_an_ephemeral_port(monkeypatch: pytest.MonkeyPatch) -> None:
    check_path = Path(__file__).resolve().parents[1] / "prototypes" / "client" / "check.py"
    spec = importlib.util.spec_from_file_location("client_check", check_path)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    class FakeListener:
        address = None
        listening = False
        inheritable = False

        def bind(self, address: tuple[str, int]) -> None:
            self.address = address

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 49381)

        def listen(self, backlog: int) -> None:
            self.listening = backlog == 128

        def set_inheritable(self, inheritable: bool) -> None:
            self.inheritable = inheritable

        def close(self) -> None:
            pass

    listener = FakeListener()
    monkeypatch.setattr(checker.socket, "socket", lambda *_args: listener)
    result = checker.reserve_smoke_listener()
    assert result is listener
    assert listener.address == ("127.0.0.1", 0)
    assert listener.getsockname()[1] != 43127
    assert listener.listening
    assert listener.inheritable


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
async def test_viewer_assets_and_native_authorization_preflight(prototype, tmp_path):
    app = FastAPI()
    # Exercise the production asset mount without requiring Node in Python tests.
    (tmp_path / "index.html").write_text('<script src="./assets/client.js"></script>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/client.js").write_text("// built client")
    prototype.configure_client(app, assets=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/client/")).status_code == 200
        assert (await client.get("/client/assets/client.js")).text == "// built client"
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
        for origin in ("tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"):
            response = await client.options(
                "/v1/matches/example/commands",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization, content-type",
                },
            )
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
            assert "POST" in response.headers["access-control-allow-methods"]
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


def test_browser_fixture_and_vendored_schema_match_shared_contracts():
    client = Path(__file__).resolve().parents[1] / "prototypes/client"
    StateResponse.model_validate_json((client / "tests/fixtures/state.json").read_text())
    CapabilitiesResponse.model_validate_json(
        (client / "tests/fixtures/capabilities.json").read_text()
    )
    lock = tomllib.loads((client / "Cargo.lock").read_text())
    tauri = next(package for package in lock["package"] if package["name"] == "tauri")
    schema = json.loads((client / "schemas/tauri-config.schema.json").read_text())
    assert schema["$id"] == f"https://schema.tauri.app/config/{tauri['version']}"


def test_missing_production_assets_report_build_command(prototype, tmp_path):
    with pytest.raises(ValueError, match="nix build .#client-web"):
        prototype.configure_client(FastAPI(), assets=tmp_path / "missing")


def test_api_schema_is_generated_from_shared_contracts():
    path = Path(__file__).resolve().parents[1] / "prototypes/client/generate_api.py"
    spec = importlib.util.spec_from_file_location("client_api_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCHEMA_PATH.read_text() == module.schema_text()
