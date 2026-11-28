"""Launch an isolated local human/AI match and supervise its owned resources."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import shutil
import signal
import socket
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import uvicorn
from pydantic import SecretStr

from aw2_lab.ai_host import prepare_pi
from aw2_lab.ai_turn_log import LogMode, color_ai_log_prefix, follow_ai_log, time_ai_turn
from aw2_lab.api.app import create_app
from aw2_lab.api.client_web import configure_client
from aw2_lab.api_contract import (
    VERIFIED_CONFIGURATION,
    MatchConfiguration,
    StateResponse,
    default_players,
)
from aw2_lab.api_validation import validate_configuration
from aw2_lab.emulator import EmulatorMode, EmulatorSettings
from aw2_lab.local_launch import LocalLaunch
from aw2_lab.map_catalog import MAPS_BY_ID
from aw2_lab.match_contract import CO_ID_VALUES, CommandStatus, MatchLifecycle, PlayerSlot
from aw2_lab.sdk import AsyncAW2Client, SDKError, WaitTimeout
from aw2_lab.turn_brief import BriefFormat, build_turn_brief, compact_turn_brief


class PlayError(RuntimeError):
    """An actionable local startup or host failure."""


class ClientLaunchMetadata(HTMLParser):
    """The selected browser build must understand the helper's launch handoff."""

    version: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and values.get("name") == "aw2-local-launch":
            self.version = values.get("content")


def validate_client_assets(directory: Path) -> None:
    index = directory.expanduser() / "index.html"
    rebuild = "nix build .#client-web --out-link prototypes/client/dist"
    if not index.is_file():
        raise PlayError(
            f"Client build missing; run `{rebuild}` or set --client-dist/AW2_CLIENT_DIST"
        )
    try:
        metadata = ClientLaunchMetadata()
        metadata.feed(index.read_text())
    except OSError, UnicodeError:
        raise PlayError(f"Cannot read client build; rebuild with `{rebuild}`") from None
    if metadata.version != "1":
        raise PlayError(
            "Client build is out of date or incompatible with automatic match connection. "
            f"Run `{rebuild}`, use a fresh nix shell, or select a current --client-dist."
        )


def positive(value: str) -> float:
    result = float(value)
    if not 0 < result < 86400:
        raise argparse.ArgumentTypeError("must be between 0 and 86400 seconds")
    return result


def turn_attempts(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return result


def port_number(value: str) -> int:
    result = int(value)
    if not 0 <= result <= 65535:
        raise argparse.ArgumentTypeError("port must be 0 (automatic) or 1–65535")
    return result


def optional_limit(value: str) -> int | None:
    return None if value == "none" else int(value)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="aw2-lab play", description=__doc__)
    result.add_argument("mode", choices=("pvp", "ai-vs-player", "ai-vs-ai"))
    result.add_argument(
        "--map",
        choices=tuple(MAPS_BY_ID),
        default="bean_island",
        help="catalog map identifier; three- and four-player maps use that many CO slots",
    )
    result.add_argument("--human-slot", type=int, choices=(1, 2, 3, 4), default=1)
    for slot, co in ((1, "andy"), (2, "max"), (3, "sami"), (4, "flak")):
        result.add_argument(f"--co-{slot}", choices=CO_ID_VALUES, default=co)
        result.add_argument(
            f"--model-{slot}", help=f"Pi provider/model for slot {slot}; overrides --model"
        )
    result.add_argument("--income", type=int, choices=range(1000, 5001, 500), default=1000)
    result.add_argument("--weather", choices=("clear", "snow", "rain", "random"), default="clear")
    result.add_argument("--day-limit", type=optional_limit, default=30, help="5–99 or none")
    result.add_argument("--capture-limit", type=optional_limit, default=None, help="12–27 or none")
    result.add_argument("--fog", action=argparse.BooleanOptionalAction, default=False)
    result.add_argument("--co-powers", action=argparse.BooleanOptionalAction, default=True)
    result.add_argument("--rom", type=Path, default=os.environ.get("AW2_ROM_PATH"))
    result.add_argument(
        "--save-profile", type=Path, default=os.environ.get("AW2_SAVE_PROFILE_PATH")
    )
    result.add_argument(
        "--client-dist",
        type=Path,
        default=os.environ.get("AW2_CLIENT_DIST", "prototypes/client/dist"),
    )
    result.add_argument("--sprite-pack", type=Path, default=os.environ.get("AW2_CLIENT_SPRITES"))
    result.add_argument("--emulator-mode", choices=tuple(EmulatorMode), default="headless")
    result.add_argument("--mgba-headless")
    result.add_argument("--mgba-windowed")
    result.add_argument("--port", type=port_number, default=0)
    result.add_argument("--bridge-port", type=port_number, default=0)
    result.add_argument(
        "--run-dir", type=Path, help="new private directory; existing directories are never reused"
    )
    result.add_argument(
        "--no-browser",
        action="store_true",
        help="save private launch links instead of opening tabs",
    )
    result.add_argument(
        "--model",
        default=os.environ.get("AW2_AI_MODEL"),
        help="Pi provider/model (otherwise use existing Pi default)",
    )
    result.add_argument("--pi-bin", default=os.environ.get("AW2_PI_BIN", "pi"))
    result.add_argument(
        "--ai-mcp-profile",
        choices=("standard", "compact"),
        default="standard",
        help="model-facing MCP tools and turn replies (default: standard)",
    )
    result.add_argument(
        "--thinking",
        choices=("off", "minimal", "low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    result.add_argument("--startup-timeout", type=positive, default=120)
    result.add_argument(
        "--ai-log",
        nargs="?",
        const="summary",
        choices=("summary", "details"),
        help="show a live AI turn log; use details to include tool payloads and available thinking",
    )
    result.add_argument("--ai-turn-timeout", type=positive, default=600)
    result.add_argument(
        "--max-ai-turns",
        type=int,
        default=0,
        help="stop after this many AI turns; 0 means unlimited",
    )
    result.add_argument(
        "--ai-turn-attempts",
        type=turn_attempts,
        default=3,
        help="host attempts per AI turn; a turn left open by an attempt is resumed within this bound",
    )
    return result


def slots_for(player_count: int) -> tuple[PlayerSlot, ...]:
    return tuple(PlayerSlot(f"slot_{index}") for index in range(1, player_count + 1))


def selected_slots(map_id: str) -> tuple[PlayerSlot, ...]:
    """Every slot the selected map advertises, in contract order."""
    return slots_for(MAPS_BY_ID[map_id].player_count)


def ai_slots(mode: str, human_slot: int, player_count: int = 2) -> tuple[PlayerSlot, ...]:
    return tuple(
        slot
        for index, slot in enumerate(slots_for(player_count), 1)
        if mode == "ai-vs-ai" or (mode == "ai-vs-player" and index != human_slot)
    )


def configuration(args: argparse.Namespace) -> MatchConfiguration:
    player_count = MAPS_BY_ID[args.map].player_count
    if args.mode != "pvp" and args.human_slot > player_count:
        raise PlayError(
            f"--human-slot {args.human_slot} exceeds the {player_count}-slot map {args.map}"
        )
    data = VERIFIED_CONFIGURATION.model_dump(mode="json")
    data["map_id"] = args.map
    data["players"] = [player.model_dump(mode="json") for player in default_players(player_count)]
    for index in range(player_count):
        data["players"][index]["co_id"] = getattr(args, f"co_{index + 1}")
    data["rules"].update(
        fog=args.fog,
        weather=args.weather,
        income_per_property=args.income,
        day_limit=args.day_limit,
        capture_limit=args.capture_limit,
        co_powers=args.co_powers,
    )
    return validate_configuration(MatchConfiguration.model_validate(data))


def default_model() -> str | None:
    provider = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent"))
    try:
        data = json.loads((provider / "settings.json").read_text())
    except OSError, ValueError:
        return None
    if not isinstance(data, dict):
        return None
    model, name = data.get("defaultModel"), data.get("defaultProvider")
    return f"{name}/{model}" if isinstance(name, str) and isinstance(model, str) else None


def bind_local(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        raise PlayError(f"Local port {port} is unavailable; choose another port") from None
    return sock


def private_file(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(text)


async def provision(
    client: AsyncAW2Client, config: MatchConfiguration, base_url: str
) -> tuple[UUID, dict[PlayerSlot, str]]:
    summary = await client.create_match(config)
    credentials = {}
    for slot in selected_slots(config.map_id):
        invitation, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        await client.invite(summary.match_id, slot, SecretStr(invitation))
        async with AsyncAW2Client(base_url, credential=token) as player:
            joined = await player.join(
                summary.match_id, slot, SecretStr(invitation), f"Player {slot.value[-1]}"
            )
        summary = joined.match
        credentials[slot] = token
    receipt = await client.start(summary.match_id, summary.revision)
    result = await client.wait_for_command(summary.match_id, receipt.command_id, timeout=120)
    if result.status is not CommandStatus.COMPLETED:
        raise PlayError(f"Match startup {result.status.value}; inspect the private run directory")
    return summary.match_id, credentials


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()


@dataclass
class TurnBudget:
    limit: int
    started: int = 0
    completed: int = 0


FIRST_TURN_INSTRUCTION = (
    "Read your assigned match and play exactly this turn. Choose gameplay actions "
    "yourself. After successfully ending this turn, stop and return immediately; do "
    "not wait for the next turn in this invocation. Stop on a finished or "
    "recovery-required match."
)
UNCOMMITTED_TURN_INSTRUCTION = (
    "This turn is still open and nothing from your previous attempt committed, so the "
    "board is at its last committed state. Reread the authoritative match state, take a "
    "different legal action or end your turn, then stop and return immediately. Stop only "
    "on a finished, closed, or recovery-required match."
)
COMMITTED_TURN_INSTRUCTION = (
    "This turn is still open after a committed action. Reread the authoritative match "
    "state, end your turn or take another legal action, then stop and return immediately. "
    "Stop only on a finished, closed, or recovery-required match."
)
AI_COMMAND_SETTLE_TIMEOUT = 30.0


async def read_after_ai_attempt(
    player: AsyncAW2Client, match_id: UUID, *, day: int | None, slot: int
) -> StateResponse:
    """Allow the next player's command to run while the AI host exits."""
    async with asyncio.timeout(AI_COMMAND_SETTLE_TIMEOUT):
        while True:
            state = await player.state(match_id)
            if state.settled:
                return state
            # During execution this is still the last committed board, so it
            # already records any completed handoff to a different turn.
            battle = state.observation.game_state.battle.value if state.observation else None
            if battle is not None and (battle.day, battle.active_player_slot) != (day, slot):
                return state
            await asyncio.sleep(0.2)


async def ai_player(
    *,
    slot: PlayerSlot,
    token: str,
    match_id: UUID,
    base_url: str,
    run_dir: Path,
    model: str,
    executable: str,
    thinking: str,
    timeout: float,
    budget: TurnBudget,
    stop: asyncio.Event,
    attempts: int = 3,
    log_mode: LogMode | None = None,
    mcp_profile: BriefFormat = "standard",
) -> None:
    if attempts < 1:
        raise ValueError("AI turn attempts must be at least 1")
    directory = run_dir / slot.value
    prompt = files("aw2_lab").joinpath("ai_prompt.md").read_text()
    host_command, env = prepare_pi(
        directory,
        url=base_url + "/mcp/",
        token=token,
        match_id=match_id,
        slot=slot,
        executable=executable,
        model=model,
        prompt=prompt,
        thinking=thinking,
        mcp_profile=mcp_profile,
    )
    base_command = [
        *host_command,
        "--print",
        "--mode",
        "json",
        "--session-id",
        str(match_id),
    ]
    async with AsyncAW2Client(base_url, credential=token) as player:
        while not stop.is_set():
            try:
                state = await player.wait_for_turn(match_id, slot, timeout=30)
            except WaitTimeout:
                continue
            if state.summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED:
                raise PlayError("Match requires recovery; saved state has been retained")
            if state.summary.lifecycle in {MatchLifecycle.FINISHED, MatchLifecycle.CLOSED}:
                return
            if stop.is_set():
                return
            if budget.limit and budget.started >= budget.limit:
                await stop.wait()
                return
            budget.started += 1
            battle = state.observation.game_state.battle.value if state.observation else None
            day = battle.day if battle else None
            own_slot = int(slot.value[-1])
            log = directory / f"turn-{budget.started}.jsonl"
            committed = battle
            changed = False
            turn_label = (
                f"[AI {own_slot} · Day {day if day is not None else '?'} · Turn {budget.started}"
            )
            turn_prefix = f"{turn_label}]"
            if log_mode:
                turn_prefix = color_ai_log_prefix(turn_prefix, own_slot)
            with time_ai_turn(log_mode, turn_prefix) as timing:
                for attempt in range(1, attempts + 1):
                    if attempt == 1:
                        instruction = FIRST_TURN_INSTRUCTION
                    elif changed:
                        instruction = COMMITTED_TURN_INSTRUCTION
                    else:
                        instruction = UNCOMMITTED_TURN_INSTRUCTION
                    brief = build_turn_brief(state, slot)
                    brief_json = (
                        compact_turn_brief(brief).model_dump_json(exclude_none=True)
                        if mcp_profile == "compact"
                        else brief.model_dump_json()
                    )
                    instruction = f"{instruction}\nCurrent turn brief: {brief_json}"
                    print(
                        f"AI {slot.value}: playing turn {budget.started} "
                        f"(attempt {attempt}/{attempts}, private log: {log})",
                        flush=True,
                    )
                    prefix = f"{turn_label} · Attempt {attempt}/{attempts}]"
                    with log.open("ab") as output:
                        async with follow_ai_log(
                            log,
                            offset=output.tell(),
                            mode=log_mode,
                            prefix=color_ai_log_prefix(prefix, own_slot) if log_mode else prefix,
                            token=token,
                            timing=timing,
                        ):
                            process = await asyncio.create_subprocess_exec(
                                *base_command,
                                instruction,
                                env=env,
                                cwd=directory,
                                stdout=output,
                                stderr=output,
                                start_new_session=True,
                            )
                            try:
                                code = await asyncio.wait_for(process.wait(), timeout)
                            except TimeoutError:
                                raise PlayError(f"AI turn timed out; inspect {log}") from None
                            finally:
                                await stop_process(process)
                    if code:
                        raise PlayError(f"AI host exited with status {code}; inspect {log}")
                    try:
                        state = await read_after_ai_attempt(
                            player, match_id, day=day, slot=own_slot
                        )
                    except TimeoutError:
                        raise PlayError(
                            f"Match command did not settle after the AI returned; inspect {log}"
                        ) from None
                    observed = (
                        state.observation.game_state.battle.value if state.observation else None
                    )
                    if state.summary.lifecycle is MatchLifecycle.RECOVERY_REQUIRED:
                        raise PlayError(f"Match requires recovery after the AI turn; inspect {log}")
                    if (
                        state.summary.lifecycle is MatchLifecycle.PLAYABLE
                        and observed
                        and observed.day == day
                        and observed.active_player_slot == own_slot
                    ):
                        if attempt < attempts:
                            changed = observed != committed
                            committed = observed
                            reason = (
                                "a committed action left it open"
                                if changed
                                else "no action committed"
                            )
                            print(
                                f"AI {slot.value}: turn {budget.started} is still open after "
                                f"{reason}; continuing with the current state "
                                f"(attempt {attempt + 1}/{attempts})",
                                flush=True,
                            )
                            continue
                        raise PlayError(
                            f"AI returned without ending its turn after {attempts} attempts; "
                            f"inspect {log}"
                        )
                    break
            budget.completed += 1
            if budget.limit and budget.completed >= budget.limit:
                stop.set()


class LocalServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        # The supervisor owns signal handling for the server and all AI children.
        yield


async def wait_ready(base_url: str, task: asyncio.Task[None], timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    async with httpx.AsyncClient(timeout=0.5, trust_env=False) as client:
        while asyncio.get_running_loop().time() < deadline:
            if task.done():
                raise PlayError(
                    "Local server stopped during startup; check the emulator diagnostic"
                )
            try:
                response = await client.get(base_url + "/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise PlayError("Timed out waiting for the local server/emulator")


async def run(args: argparse.Namespace) -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config = configuration(args)
    if not args.rom or not args.rom.expanduser().is_file():
        raise PlayError("Provide --rom or AW2_ROM_PATH pointing to your local ROM")
    validate_client_assets(args.client_dist)
    if args.save_profile and (
        not args.save_profile.expanduser().is_file()
        or args.save_profile.suffix.lower() not in {".sav", ".sps"}
    ):
        raise PlayError("Save profile must be an existing .sav or .sps file")
    if args.max_ai_turns < 0:
        raise PlayError("--max-ai-turns must be nonnegative")
    slots = ai_slots(args.mode, args.human_slot, MAPS_BY_ID[args.map].player_count)
    executable = shutil.which(args.pi_bin) if slots else None
    models = {
        slot: getattr(args, f"model_{slot.value[-1]}") or args.model or default_model()
        for slot in slots
    }
    if slots and (not executable or any(not value for value in models.values())):
        raise PlayError(
            "AI requires Pi and a configured default model, --model, or --model-1/--model-2"
        )
    http_socket = bind_local(args.port)
    try:
        with bind_local(args.bridge_port) as bridge_socket:
            bridge_port = bridge_socket.getsockname()[1]
        base_url = f"http://127.0.0.1:{http_socket.getsockname()[1]}"
        root = args.run_dir or Path(
            os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
        ) / "aw2-lab/play" / str(uuid4())
        root = root.expanduser().resolve()
        if root.exists():
            raise PlayError(
                "Run directory already exists; choose a new directory to preserve existing games"
            )
        root.mkdir(parents=True, mode=0o700)
        operator = secrets.token_urlsafe(32)
        private_file(root / "operator", operator)
        print(f"Private run directory: {root}", flush=True)
        app = create_app(
            settings=EmulatorSettings(
                rom_path=args.rom.expanduser().resolve(),
                save_profile_path=args.save_profile.expanduser().resolve()
                if args.save_profile
                else None,
                mode=EmulatorMode(args.emulator_mode),
                bridge_port=bridge_port,
                headless_executable=args.mgba_headless,
                windowed_executable=args.mgba_windowed,
                suppress_emulator_output=True,
            ),
            storage_root=root / "storage",
            operator_secret_file=root / "operator",
            api_base_url=base_url,
        )
        configure_client(
            app, assets=args.client_dist.expanduser().resolve(), sprite_pack=args.sprite_pack
        )
        launch = LocalLaunch(app, base_url, operator)
        server = LocalServer(
            uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=5)
        )
        server_task = asyncio.create_task(server.serve(sockets=[http_socket]))
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        signals = (signal.SIGINT, signal.SIGTERM)
        previous_signals = {item: signal.getsignal(item) for item in signals}
        for item in signals:
            loop.add_signal_handler(item, stop.set)
        tasks: list[asyncio.Task[None]] = []
        failure: asyncio.Future[BaseException] = loop.create_future()

        async def setup_match() -> tuple[UUID, dict[PlayerSlot, str]]:
            await wait_ready(base_url, server_task, args.startup_timeout)
            async with AsyncAW2Client(base_url, credential=operator) as client:
                return await provision(client, config, base_url)

        stop_task = asyncio.create_task(stop.wait())
        setup_task = asyncio.create_task(setup_match())
        try:
            await asyncio.wait(
                (setup_task, stop_task, server_task), return_when=asyncio.FIRST_COMPLETED
            )
            if stop.is_set():
                return
            if server_task.done():
                raise PlayError(
                    "Local server stopped during startup; check the emulator diagnostic"
                )
            match_id, credentials = await setup_task
            launch.match_id = match_id
            for slot, token in credentials.items():
                private_file(root / f"{slot.value}.token", token)
            views = {}
            for slot in (PlayerSlot.SLOT_1, PlayerSlot.SLOT_2):
                if slot not in slots:
                    views[f"Player {slot.value[-1]}"] = launch.browser_url(credentials[slot])
            if args.mode == "ai-vs-ai":
                private_file(root / "watch.token", launch.watch_token)
                views["Watch (read only)"] = launch.browser_url(launch.watch_token)
            private_file(root / "views.json", json.dumps(views, indent=2) + "\n")
            private_file(
                root / "match.json",
                json.dumps(
                    {
                        "match_id": str(match_id),
                        "base_url": base_url,
                        "mode": args.mode,
                        "bridge_port": bridge_port,
                        "bridge_instance": app.state.emulator_launcher.instance_nonce,
                    }
                )
                + "\n",
            )
            print(
                f"Match {match_id} ready: {args.mode}, {args.map}\nClient: {base_url}/client/\nPrivate launch links (one use, five minutes): {root / 'views.json'}\nPress Ctrl-C to stop owned processes; checkpoints are retained.",
                flush=True,
            )
            if not args.no_browser:
                for name, url in views.items():
                    if not webbrowser.open_new_tab(url):
                        print(
                            f"Could not open {name}; use its private link in views.json", flush=True
                        )
            budget = TurnBudget(args.max_ai_turns)

            def host_done(task: asyncio.Task[None]) -> None:
                if not task.cancelled() and task.exception() is not None and not failure.done():
                    error = task.exception()
                    assert error is not None
                    failure.set_result(error)

            for slot in slots:
                model = models[slot]
                assert executable and model
                task = asyncio.create_task(
                    ai_player(
                        slot=slot,
                        token=credentials[slot],
                        match_id=match_id,
                        base_url=base_url,
                        run_dir=root,
                        model=model,
                        executable=executable,
                        thinking=args.thinking,
                        timeout=args.ai_turn_timeout,
                        budget=budget,
                        stop=stop,
                        attempts=args.ai_turn_attempts,
                        log_mode=args.ai_log,
                        mcp_profile=args.ai_mcp_profile,
                    )
                )
                task.add_done_callback(host_done)
                tasks.append(task)
            try:
                await asyncio.wait(
                    (stop_task, server_task, failure), return_when=asyncio.FIRST_COMPLETED
                )
                if failure.done():
                    raise failure.result()
                if server_task.done() and not stop.is_set():
                    raise PlayError("Local server stopped unexpectedly")
            finally:
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
        finally:
            setup_task.cancel()
            stop_task.cancel()
            await asyncio.gather(setup_task, stop_task, return_exceptions=True)
            for item in signals:
                loop.remove_signal_handler(item)
                signal.signal(item, previous_signals[item])
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            app.state.match_controller.stop_event_streams()
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(server_task), 20)
            except TimeoutError:
                server_task.cancel()
                await asyncio.gather(server_task, return_exceptions=True)
    finally:
        http_socket.close()


def main(argv: list[str] | None = None) -> None:
    cli = parser()
    args = cli.parse_args(argv)
    old_mask = os.umask(0o077)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (PlayError, SDKError, OSError, ValueError) as error:
        cli.exit(1, f"aw2-lab play: {error}\n")
    finally:
        os.umask(old_mask)
