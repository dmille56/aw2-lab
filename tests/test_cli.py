from pathlib import Path

import pytest

from aw2_lab import cli


def invoke_cli(
    monkeypatch: pytest.MonkeyPatch,
    rom: Path,
    *args: str,
    env_rom: str | None = None,
    env_mode: str | None = None,
    env_console: str | None = None,
) -> tuple[object, dict[str, object]]:
    captured: dict[str, object] = {}
    monkeypatch.setattr("sys.argv", ["aw2-lab", *args])
    monkeypatch.setenv("AW2_ROM_PATH", env_rom or str(rom))
    if env_mode is None:
        monkeypatch.delenv("AW2_EMULATOR_MODE", raising=False)
    else:
        monkeypatch.setenv("AW2_EMULATOR_MODE", env_mode)
    if env_console is None:
        monkeypatch.delenv("AW2_MGBA_SCRIPTING_CONSOLE", raising=False)
    else:
        monkeypatch.setenv("AW2_MGBA_SCRIPTING_CONSOLE", env_console)
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda application, **kwargs: captured.update(app=application, **kwargs)
    )
    cli.main()
    return captured["app"], captured


def test_cli_requires_a_rom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["aw2-lab"])
    monkeypatch.delenv("AW2_ROM_PATH", raising=False)

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2


def test_rom_environment_variable_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()

    application, _ = invoke_cli(monkeypatch, rom, env_rom=str(rom))

    assert application.state.emulator_settings.rom_path == rom.resolve()
    output = capsys.readouterr().out
    assert "Emulator settings:" in output
    assert f"rom_path: {rom.resolve()}" in output
    assert "mode: headless" in output
    assert "headless_executable: None" in output
    assert "windowed_executable: None" in output
    assert "bridge_script: None" in output
    assert "show_scripting_console: False" in output


def test_cli_rom_overrides_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cli_rom = tmp_path / "cli.gba"
    env_rom = tmp_path / "env.gba"
    cli_rom.touch()
    env_rom.touch()

    application, _ = invoke_cli(monkeypatch, cli_rom, "--rom", str(cli_rom), env_rom=str(env_rom))

    assert application.state.emulator_settings.rom_path == cli_rom.resolve()


def test_missing_rom_file_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "missing.gba"
    monkeypatch.setattr("sys.argv", ["aw2-lab", "--rom", str(rom)])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2


def test_emulator_mode_cli_overrides_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()

    application, _ = invoke_cli(
        monkeypatch, rom, "--emulator-mode", "windowed", env_mode="headless"
    )

    assert application.state.emulator_settings.mode == "windowed"
    assert "mode: windowed" in capsys.readouterr().out


def test_emulator_mode_uses_environment_then_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()

    configured_app, _ = invoke_cli(monkeypatch, rom, env_mode="windowed")
    default_app, _ = invoke_cli(monkeypatch, rom)

    assert configured_app.state.emulator_settings.mode == "windowed"
    assert default_app.state.emulator_settings.mode == "headless"


def test_invalid_emulator_mode_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()
    monkeypatch.setenv("AW2_ROM_PATH", str(rom))
    monkeypatch.setenv("AW2_EMULATOR_MODE", "invalid")
    monkeypatch.setattr("sys.argv", ["aw2-lab"])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "AW2_EMULATOR_MODE must be 'headless' or 'windowed'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "env_console", "expected"),
    [
        ((), None, False),
        ((), "true", True),
        (("--scripting-console",), None, True),
        (("--no-scripting-console",), "true", False),
    ],
)
def test_scripting_console_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: tuple[str, ...],
    env_console: str | None,
    expected: bool,
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()

    application, _ = invoke_cli(monkeypatch, rom, *args, env_console=env_console)

    assert application.state.emulator_settings.show_scripting_console is expected


def test_invalid_scripting_console_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rom = tmp_path / "aw2.gba"
    rom.touch()
    monkeypatch.setenv("AW2_ROM_PATH", str(rom))
    monkeypatch.setenv("AW2_MGBA_SCRIPTING_CONSOLE", "sometimes")
    monkeypatch.setattr("sys.argv", ["aw2-lab"])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
