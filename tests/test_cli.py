from pathlib import Path

import pytest

from aw2_lab import cli
from aw2_lab.api import app as api_app
from aw2_lab.rom_profile import AW2_US_REVISION_0, UnsupportedRomError


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
    monkeypatch.setattr(api_app, "select_rom_profile", lambda _: AW2_US_REVISION_0)
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


def test_unsupported_rom_is_reported_as_cli_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rom = tmp_path / "unsupported.gba"
    rom.touch()
    monkeypatch.setenv("AW2_ROM_PATH", str(rom))
    monkeypatch.setattr("sys.argv", ["aw2-lab"])

    def reject_rom(_: Path) -> None:
        raise UnsupportedRomError("ROM SHA-256 deadbeef is not supported")

    monkeypatch.setattr(api_app, "select_rom_profile", reject_rom)

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "ROM SHA-256 deadbeef is not supported" in capsys.readouterr().err


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


def dump_arguments(output: Path) -> list[str]:
    return [
        "aw2-lab",
        "dump-memory",
        "--range",
        "0x02000000:16",
        "--output",
        str(output),
        "--emulator-mode",
        "headless",
        "--emulator-build",
        "pinned build",
        "--checkpoint",
        "initial boot",
        "--reproduction",
        "No inputs",
    ]


def test_dump_cli_captures_without_starting_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from aw2_lab import research
    from aw2_lab.bridge import LuaBridgeClient, MemorySnapshot

    async def snapshot(self: LuaBridgeClient, ranges: list[tuple[int, int]]) -> MemorySnapshot:
        assert ranges == [(0x02000000, 16)]
        return MemorySnapshot(5, (bytes(range(16)),))

    monkeypatch.setattr(research, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    monkeypatch.setattr(LuaBridgeClient, "read_memory_snapshot", snapshot)
    monkeypatch.setenv("AW2_ROM_PATH", "unused.gba")
    monkeypatch.setenv("AW2_MGBA_SCRIPTING_CONSOLE", "invalid-for-server")
    output = tmp_path / "dump.json"
    monkeypatch.setattr("sys.argv", dump_arguments(output))
    cli.main()
    assert json.loads(output.read_text())["frame"] == 5
    assert "frame 5" in capsys.readouterr().out


@pytest.mark.parametrize("failure", [OSError("disk full"), ConnectionError("unused")])
def test_dump_cli_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    from aw2_lab.bridge import BridgeError

    if isinstance(failure, ConnectionError):
        failure = BridgeError("bridge unavailable")

    async def capture(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(cli, "capture_memory_dump", capture)
    monkeypatch.setenv("AW2_ROM_PATH", "unused.gba")
    output = tmp_path / "dump.json"
    monkeypatch.setattr("sys.argv", dump_arguments(output))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert str(failure) in capsys.readouterr().err
    assert not output.exists()


def test_dump_range_parser() -> None:
    import argparse

    assert cli._memory_range("0x02000000:16") == (0x02000000, 16)
    assert cli._memory_range("32:0x10") == (32, 16)
    with pytest.raises(argparse.ArgumentTypeError):
        cli._memory_range("invalid")


@pytest.mark.parametrize(
    "missing",
    [
        "--emulator-build",
        "--checkpoint",
        "--reproduction",
        "--emulator-mode",
        "--range",
        "--output",
    ],
)
def test_dump_cli_requires_capture_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    arguments = dump_arguments(tmp_path / "dump.json")
    index = arguments.index(missing)
    del arguments[index : index + 2]
    monkeypatch.setattr("sys.argv", arguments)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_diff_memory_cli_prints_controlled_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import replace

    from aw2_lab.emulator import EmulatorMode
    from aw2_lab.research import DumpRange, MemoryDump, ResearchContext, write_memory_dump

    context = ResearchContext(EmulatorMode.HEADLESS, "build", "before", "No inputs")
    before = MemoryDump(
        1,
        "2026-10-21T00:00:00+00:00",
        "test",
        AW2_US_REVISION_0,
        context,
        10,
        (DumpRange(0x02000000, 2, "0001"),),
    )
    after = replace(
        before,
        frame=12,
        context=replace(context, checkpoint="after", reproduction="Capture after event"),
        ranges=(DumpRange(0x02000000, 2, "0002"),),
    )
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    write_memory_dump(before, before_path)
    write_memory_dump(after, after_path)
    monkeypatch.setattr("sys.argv", ["aw2-lab", "diff-memory", str(before_path), str(after_path)])

    cli.main()

    output = capsys.readouterr().out
    assert "Changed bytes: 1" in output
    assert "0x02000001  0x01    0x02" in output


def test_diff_memory_cli_reports_invalid_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before_path = tmp_path / "before.json"
    before_path.write_text("not JSON")
    after_path = tmp_path / "after.json"
    after_path.write_text("{}")
    monkeypatch.setattr("sys.argv", ["aw2-lab", "diff-memory", str(before_path), str(after_path)])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "invalid JSON memory dump" in capsys.readouterr().err
