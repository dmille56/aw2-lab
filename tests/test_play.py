"""Match launcher orchestration and failure paths need no ROM or model service."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from aw2_lab import play
from aw2_lab.ai_host import prepare_pi
from aw2_lab.match_contract import CO_ID_VALUES, CommandStatus, PlayerSlot


@pytest.mark.parametrize(
    "mode,human,expected",
    [
        ("pvp", 1, ()),
        ("ai-vs-player", 1, (PlayerSlot.SLOT_2,)),
        ("ai-vs-player", 2, (PlayerSlot.SLOT_1,)),
        ("ai-vs-ai", 1, (PlayerSlot.SLOT_1, PlayerSlot.SLOT_2)),
    ],
)
def test_mode_assignments(mode, human, expected):
    assert play.ai_slots(mode, human) == expected


def test_configuration_and_invalid_combinations():
    args = play.parser().parse_args(
        ["pvp", "--map", "rainy_haven", "--co-1", "lash", "--income", "5000", "--day-limit", "none"]
    )
    config = play.configuration(args)
    assert config.map_id == "rainy_haven" and config.players[0].co_id == "lash"
    assert config.rules.income_per_property == 5000 and config.rules.day_limit is None
    assert all(player.control == "external" for player in config.players)
    with pytest.raises(ValueError):
        play.configuration(play.parser().parse_args(["pvp", "--day-limit", "2"]))
    for flags in (
        ["invalid"],
        ["pvp", "--map", "not_a_catalog_map"],
        ["pvp", "--port", "99999"],
        ["pvp", "--ai-turn-timeout", "nan"],
    ):
        with pytest.raises(SystemExit):
            play.parser().parse_args(flags)


@pytest.mark.parametrize("map_id,count", [("bean_island", 2), ("pipe_maze", 4)])
def test_multislot_maps_use_every_advertised_slot(map_id, count):
    config = play.configuration(play.parser().parse_args(["pvp", "--map", map_id]))
    assert len(config.players) == count
    assert tuple(player.slot for player in config.players) == play.slots_for(count)
    assert play.selected_slots(map_id) == tuple(player.slot for player in config.players)
    assert {player.co_id for player in config.players} <= set(CO_ID_VALUES)


def test_four_player_ai_mode_drives_the_other_three_slots():
    args = play.parser().parse_args(["ai-vs-player", "--map", "pipe_maze", "--human-slot", "3"])
    config = play.configuration(args)
    assert play.ai_slots(args.mode, args.human_slot, len(config.players)) == (
        PlayerSlot.SLOT_1,
        PlayerSlot.SLOT_2,
        PlayerSlot.SLOT_4,
    )
    bad = play.parser().parse_args(["ai-vs-player", "--map", "bean_island", "--human-slot", "3"])
    with pytest.raises(play.PlayError):
        play.configuration(bad)


def test_private_files_and_default_model(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path))
    assert play.default_model() is None
    (tmp_path / "settings.json").write_text(
        json.dumps({"defaultProvider": "test", "defaultModel": "model"})
    )
    assert play.default_model() == "test/model"
    path = tmp_path / "token"
    play.private_file(path, "secret")
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        play.private_file(path, "replacement")
    assert path.read_text() == "secret"


def test_pi_hosts_keep_credentials_and_histories_separate(tmp_path, monkeypatch):
    provider = tmp_path / "provider"
    provider.mkdir()
    (provider / "auth.json").write_text("{}")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(provider))
    commands = []
    for slot in (PlayerSlot.SLOT_1, PlayerSlot.SLOT_2):
        token = slot.value * 8
        directory = tmp_path / slot.value
        command, env = prepare_pi(
            directory,
            url="http://127.0.0.1:1234/mcp/",
            token=token,
            match_id=uuid4(),
            slot=slot,
            executable="pi",
            model="test/model",
            prompt="Play AW2",
        )
        commands.append(command)
        assert env["AW2_PLAYER_TOKEN"] == token
        assert token not in " ".join(command)
        config = (directory / "agent/mcp.json").read_text()
        assert token not in config and "${AW2_PLAYER_TOKEN}" in config
        assert (directory / "agent/auth.json").is_symlink()
        assert "--no-builtin-tools" in command and "--no-context-files" in command
    assert commands[0] != commands[1]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [CommandStatus.COMPLETED, CommandStatus.REJECTED])
async def test_provision_uses_distinct_join_credentials_and_follows_start_receipt(
    monkeypatch, status
):
    mid = uuid4()
    summary = SimpleNamespace(match_id=mid, revision=0)
    operator = SimpleNamespace(
        create_match=AsyncMock(return_value=summary),
        invite=AsyncMock(),
        start=AsyncMock(return_value=SimpleNamespace(command_id=uuid4())),
        wait_for_command=AsyncMock(return_value=SimpleNamespace(status=status)),
    )
    joined = []

    class Player:
        def __init__(self, base_url, credential):
            self.token = credential

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def join(self, match_id, slot, invitation, name):
            joined.append((slot, self.token, invitation.get_secret_value()))
            summary.revision += 1
            return SimpleNamespace(match=summary)

    monkeypatch.setattr(play, "AsyncAW2Client", Player)
    if status is CommandStatus.COMPLETED:
        actual, credentials = await play.provision(
            operator, play.VERIFIED_CONFIGURATION, "http://test"
        )
        assert actual == mid and len(set(credentials.values())) == 2
    else:
        with pytest.raises(play.PlayError, match="startup rejected"):
            await play.provision(operator, play.VERIFIED_CONFIGURATION, "http://test")
    assert len({token for _, token, _ in joined}) == 2
    assert all(token != invitation for _, token, invitation in joined)
    operator.start.assert_awaited_once_with(mid, 2)
    operator.wait_for_command.assert_awaited_once()


@pytest.mark.anyio
async def test_startup_failure_stops_owned_server_and_keeps_private_state(tmp_path, monkeypatch):
    rom, assets = tmp_path / "rom.gba", tmp_path / "assets"
    rom.touch()
    assets.mkdir()
    (assets / "index.html").write_text('<meta name="aw2-local-launch" content="1">')
    root = tmp_path / "run"
    args = play.parser().parse_args(
        ["pvp", "--rom", str(rom), "--client-dist", str(assets), "--run-dir", str(root)]
    )

    class Socket:
        def getsockname(self):
            return ("127.0.0.1", 12345)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    servers = []

    class Server:
        def __init__(self, config):
            self.should_exit = False
            self.stopped = False
            servers.append(self)

        async def serve(self, **kwargs):
            while not self.should_exit:
                await asyncio.sleep(0)
            self.stopped = True

    monkeypatch.setattr(play, "bind_local", lambda _: Socket())
    monkeypatch.setattr(play, "create_app", lambda **_: FastAPI())
    monkeypatch.setattr(play, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr(play, "LocalServer", Server)
    monkeypatch.setattr(play, "wait_ready", AsyncMock(side_effect=play.PlayError("startup failed")))
    with pytest.raises(play.PlayError, match="startup failed"):
        await play.run(args)
    assert servers[0].stopped
    assert (root / "operator").stat().st_mode & 0o077 == 0
    with pytest.raises(play.PlayError, match="already exists"):
        await play.run(args)
    assert len(servers) == 1


@pytest.mark.anyio
async def test_stop_process_terminates_only_its_own_process(monkeypatch):
    calls = []

    class Process:
        returncode = None
        pid = 123456

        async def wait(self):
            self.returncode = 0

    monkeypatch.setattr(play.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    process = Process()
    await play.stop_process(process)
    assert calls == [(123456, play.signal.SIGTERM)]


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["ended", "unchanged", "failed", "timeout"])
async def test_ai_turn_scheduling_follows_authoritative_state_and_cleans_up(
    tmp_path, monkeypatch, outcome
):
    from aw2_lab.match_contract import MatchLifecycle

    before = SimpleNamespace(
        settled=True,
        summary=SimpleNamespace(lifecycle=MatchLifecycle.PLAYABLE),
        observation=SimpleNamespace(
            game_state=SimpleNamespace(
                battle=SimpleNamespace(value=SimpleNamespace(day=1, active_player_slot=1))
            )
        ),
    )
    after = SimpleNamespace(
        settled=True,
        summary=before.summary,
        observation=SimpleNamespace(
            game_state=SimpleNamespace(
                battle=SimpleNamespace(
                    value=SimpleNamespace(
                        day=1, active_player_slot=1 if outcome == "unchanged" else 2
                    )
                )
            )
        ),
    )

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def wait_for_turn(self, *args, **kwargs):
            return before

        async def state(self, *args):
            return after

    monkeypatch.setattr(play, "AsyncAW2Client", lambda *a, **kw: Client())
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "provider"))
    called = []

    class Process:
        returncode = None
        pid = 987654

        async def wait(self):
            if outcome == "timeout":
                await asyncio.Event().wait()
            self.returncode = 1 if outcome == "failed" else 0
            return self.returncode

    async def spawn(*args, **kwargs):
        called.append((args, kwargs))
        return Process()

    monkeypatch.setattr(play.asyncio, "create_subprocess_exec", spawn)
    cleanup = AsyncMock()
    monkeypatch.setattr(play, "stop_process", cleanup)
    stop = asyncio.Event()
    run = play.ai_player(
        slot=PlayerSlot.SLOT_1,
        token="p" * 40,
        match_id=uuid4(),
        base_url="http://test",
        run_dir=tmp_path,
        model="test/model",
        executable="pi",
        thinking="low",
        timeout=0.01,
        budget=play.TurnBudget(1),
        stop=stop,
        attempts=1,
    )
    if outcome == "ended":
        await run
        assert stop.is_set()
    else:
        with pytest.raises(play.PlayError):
            await run
    cleanup.assert_awaited_once()
    command, options = called[0]
    assert "--print" in command and "--session-id" in command
    assert "p" * 40 not in " ".join(command)
    assert options["env"]["AW2_PLAYER_TOKEN"] == "p" * 40


def _turn_state(*, lifecycle, active_slot: int, day: int = 1, settled: bool = True):
    return SimpleNamespace(
        settled=settled,
        summary=SimpleNamespace(lifecycle=lifecycle),
        observation=SimpleNamespace(
            game_state=SimpleNamespace(
                battle=SimpleNamespace(
                    value=SimpleNamespace(day=day, active_player_slot=active_slot)
                )
            )
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [
        ("rollback_then_end", None),
        ("always_open", "without ending its turn"),
        ("recovery_after_rollback", "requires recovery"),
    ],
)
async def test_ai_host_continues_a_turn_rolled_back_by_aw2(
    tmp_path, monkeypatch, outcome, expected_error
) -> None:
    from aw2_lab.match_contract import MatchLifecycle

    open_turn = _turn_state(lifecycle=MatchLifecycle.PLAYABLE, active_slot=1)
    if outcome == "rollback_then_end":
        turns = [open_turn, _turn_state(lifecycle=MatchLifecycle.PLAYABLE, active_slot=2)]
    elif outcome == "always_open":
        turns = [open_turn] * 3
    else:
        turns = [
            open_turn,
            _turn_state(lifecycle=MatchLifecycle.RECOVERY_REQUIRED, active_slot=1),
        ]
    queue = list(turns)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def wait_for_turn(self, *args, **kwargs):
            return open_turn

        async def state(self, *args):
            return queue.pop(0) if queue else turns[-1]

    monkeypatch.setattr(play, "AsyncAW2Client", lambda *a, **kw: Client())
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "provider"))
    commands = []

    class Process:
        returncode = None
        pid = 987654

        async def wait(self):
            self.returncode = 0
            return 0

    async def spawn(*args, **kwargs):
        commands.append(args)
        return Process()

    monkeypatch.setattr(play.asyncio, "create_subprocess_exec", spawn)
    stop = asyncio.Event()
    budget = play.TurnBudget(1)
    run = play.ai_player(
        slot=PlayerSlot.SLOT_1,
        token="p" * 40,
        match_id=uuid4(),
        base_url="http://test",
        run_dir=tmp_path,
        model="test/model",
        executable="pi",
        thinking="low",
        timeout=5,
        budget=budget,
        stop=stop,
        attempts=3,
    )
    if expected_error:
        with pytest.raises(play.PlayError, match=expected_error):
            await run
    else:
        await run
        assert stop.is_set()
        assert budget.completed == 1
    assert len(commands) == len(turns)
    assert commands[0][-1] == play.FIRST_TURN_INSTRUCTION
    if len(commands) > 1:
        assert "rolled back" in commands[1][-1]
    assert (tmp_path / PlayerSlot.SLOT_1.value / "turn-1.jsonl").exists()


def test_ai_prompt_teaches_the_host_to_resume_a_rolled_back_turn() -> None:
    from importlib.resources import files
    from pathlib import Path

    prompts = (
        files("aw2_lab").joinpath("ai_prompt.md").read_text(),
        (Path(__file__).resolve().parent.parent / "examples" / "pi-host" / "system.md").read_text(),
    )
    for prompt in prompts:
        assert "rolled_back" in prompt
        assert "recovery_required" in prompt


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["pvp", "ai-vs-player", "ai-vs-ai"])
async def test_stale_client_is_rejected_before_creating_or_starting_a_match(
    tmp_path, monkeypatch, mode
):
    rom = tmp_path / "rom.gba"
    rom.touch()
    assets = tmp_path / "old-client"
    assets.mkdir()
    (assets / "index.html").write_text('<html><div id="root"></div></html>')
    root = tmp_path / "run"
    args = play.parser().parse_args(
        [mode, "--rom", str(rom), "--client-dist", str(assets), "--run-dir", str(root)]
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("A stale client must fail before binding ports or starting anything")

    monkeypatch.setattr(play, "bind_local", unexpected)
    monkeypatch.setattr(play, "create_app", unexpected)
    with pytest.raises(play.PlayError, match="automatic match connection"):
        await play.run(args)
    assert not root.exists()


def test_client_handoff_version_is_required_and_parsed_as_html(tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<META content='1' name='aw2-local-launch'>")
    play.validate_client_assets(tmp_path)
    index.write_text('<meta name="aw2-local-launch" content="2">')
    with pytest.raises(play.PlayError, match="incompatible"):
        play.validate_client_assets(tmp_path)
    index.unlink()
    with pytest.raises(play.PlayError, match="Client build missing"):
        play.validate_client_assets(tmp_path)
