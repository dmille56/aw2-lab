"""ROM-independent checks for the prototype server's ROM configuration."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI


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
