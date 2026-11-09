"""Local host configuration isolates sessions and keeps tokens out of files."""

import json
import runpy
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


def prepare(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "examples" / "pi-host", tmp_path / "examples" / "pi-host")
    main = runpy.run_path(str(root / "examples" / "pi_host.py"))["main"]
    monkeypatch.setitem(main.__globals__, "ROOT", tmp_path)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "provider"))
    token_file = tmp_path / "token"
    token_file.write_text("x" * 40)
    token_file.chmod(0o600)
    args = [
        "pi_host.py",
        "--match-id",
        str(uuid4()),
        "--slot",
        "slot_1",
        "--token-file",
        str(token_file),
    ]
    return main, args


def test_prepare_keeps_token_out_of_config_and_separates_slots(monkeypatch, tmp_path):
    main, args = prepare(monkeypatch, tmp_path)
    for slot in ("slot_1", "slot_2"):
        args[4] = slot
        monkeypatch.setattr(sys, "argv", [*args, "--prepare-only"])
        assert main() == 0
        run_dir = tmp_path / ".local" / "aw2-pi" / args[2] / slot
        assert run_dir.stat().st_mode & 0o077 == 0
        config = (run_dir / "agent" / "mcp.json").read_text()
        assert "x" * 40 not in config
        assert set(json.loads(config)["mcpServers"]) == {"aw2"}
        assert "${AW2_PLAYER_TOKEN}" in config


def test_launcher_exposes_only_aw2_and_passes_token_to_transport(monkeypatch, tmp_path):
    main, args = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(shutil, "which", lambda _: "/test/pi")
    monkeypatch.setattr("os.chdir", lambda _: None)
    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"role": "player", "match_id": args[2], "player_slot": "slot_1"},
        ),
    )

    def launch(executable, command, env):
        assert executable == "/test/pi"
        assert command[command.index("--tools") + 1] == "mcp__aw2__*"
        assert "--no-builtin-tools" in command
        assert "--no-extensions" in command
        assert command[command.index("--extension") + 1] == "builtin:mcp"
        assert "--no-context-files" in command
        assert env["AW2_PLAYER_TOKEN"] == "x" * 40
        assert "x" * 40 not in " ".join(command)
        raise InterruptedError("captured launch")

    monkeypatch.setattr("os.execvpe", launch)
    with pytest.raises(InterruptedError, match="captured launch"):
        main()


def test_rejects_remote_endpoint_before_creating_host(monkeypatch, tmp_path):
    main, args = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", [*args, "--url", "http://remote.example/mcp/"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("role,slot", [("operator", None), ("player", "slot_2")])
def test_rejects_wrong_player_identity(monkeypatch, tmp_path, role, slot):
    main, args = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", [*args, "--check"])
    monkeypatch.setattr(shutil, "which", lambda _: "/test/pi")
    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"role": role, "match_id": args[2], "player_slot": slot},
        ),
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
