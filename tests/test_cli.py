from pathlib import Path

import pytest

from aw2_lab import cli


def invoke_cli(monkeypatch: pytest.MonkeyPatch, *args: str, env_rom: str | None = None) -> object:
    captured: dict[str, object] = {}
    monkeypatch.setattr("sys.argv", ["aw2-lab", *args])
    if env_rom is None:
        monkeypatch.delenv("AW2_ROM_PATH", raising=False)
    else:
        monkeypatch.setenv("AW2_ROM_PATH", env_rom)
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs)
    )
    cli.main()
    return captured["app"]


def test_cli_starts_without_a_rom(monkeypatch: pytest.MonkeyPatch) -> None:
    application = invoke_cli(monkeypatch)

    assert application.state.rom_path is None


def test_rom_environment_variable_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()

    application = invoke_cli(monkeypatch, env_rom=str(rom))

    assert application.state.rom_path == rom.resolve()


def test_cli_rom_overrides_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cli_rom = tmp_path / "cli.gba"
    env_rom = tmp_path / "env.gba"
    cli_rom.touch()
    env_rom.touch()

    application = invoke_cli(monkeypatch, "--rom", str(cli_rom), env_rom=str(env_rom))

    assert application.state.rom_path == cli_rom.resolve()


def test_missing_rom_file_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        invoke_cli(monkeypatch, "--rom", str(tmp_path / "missing.gba"))

    assert error.value.code == 2
