"""Opt-in, paid comparison of model turns from identical AW2 checkpoints."""

import asyncio
import json
import os
from pathlib import Path
from secrets import token_urlsafe
from time import perf_counter
from uuid import UUID

import pytest
from pydantic import SecretStr
from test_mcp_live_acceptance import sdk_action, unit_identity
from test_sdk_live_integration import coords, server

from aw2_lab.ai_host import COMPACT_AI_TOOLS, prepare_pi
from aw2_lab.capture_rules import CAPTURE_UNIT_TYPES
from aw2_lab.match_contract import (
    CommandStatus,
    Coordinate,
    EndTurnAction,
    MoveAttackAction,
    MoveCaptureAction,
    MoveWaitAction,
    PlayerSlot,
    PurchaseAction,
)
from aw2_lab.play import PlayError, TurnBudget, ai_player
from aw2_lab.sdk import AsyncAW2Client

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_AI_MCP_BENCHMARK") != "1",
    reason="opt in to eight paid Pi model turns and provide a supported ROM",
)

MODEL = "openai/gpt-6-luna"
SLOT = PlayerSlot.SLOT_1
CAPTURE_TILE = (5, 4)
OBSERVATION_TOOLS = {*COMPACT_AI_TOOLS, "wait_for_turn", "inspect_match", "list_checkpoints"}


async def restore(admin, match_id, checkpoint_id):
    state = await admin.state(match_id)
    receipt = await admin.restore_checkpoint(match_id, checkpoint_id, state.summary.revision)
    result = await admin.wait_for_command(match_id, receipt.command_id, timeout=60)
    assert result.status is CommandStatus.COMPLETED
    return await admin.state(match_id)


async def prepare_midgame(red, blue, admin, match_id):
    async def act(player, action):
        return await sdk_action(player, match_id, action)

    await act(red, PurchaseAction(property=Coordinate(x=3, y=6), unit_type="Infantry"))
    await act(red, PurchaseAction(property=Coordinate(x=1, y=6), unit_type="Tank"))
    await act(red, EndTurnAction())
    await act(blue, PurchaseAction(property=Coordinate(x=12, y=6), unit_type="Tank"))
    await act(blue, EndTurnAction())
    state = await red.state(match_id)
    infantry = unit_identity(state, 1, 1)
    tank = unit_identity(state, 5, 1)
    opposing_tank = unit_identity(state, 5, 2)
    await act(red, MoveWaitAction(unit_id=infantry, path=coords([(3, 5), (4, 5)])))
    await act(
        red,
        MoveWaitAction(unit_id=tank, path=coords([(1, 7), (1, 8), (1, 9), (2, 9), (3, 9), (4, 9)])),
    )
    await act(red, EndTurnAction())
    await act(
        blue,
        MoveWaitAction(
            unit_id=opposing_tank, path=coords([(12, 7), (12, 8), (12, 9), (11, 9), (10, 9)])
        ),
    )
    await act(blue, EndTurnAction())
    await act(red, MoveCaptureAction(unit_id=infantry, path=coords([(5, 5), CAPTURE_TILE])))
    await act(
        red,
        MoveWaitAction(unit_id=tank, path=coords([(5, 9), (5, 8), (5, 7), (5, 6), (5, 5), (6, 5)])),
    )
    await act(red, EndTurnAction())
    await act(
        blue,
        MoveWaitAction(
            unit_id=opposing_tank, path=coords([(10, 8), (10, 7), (10, 6), (10, 5), (9, 5), (8, 5)])
        ),
    )
    await act(blue, EndTurnAction())
    state = await red.state(match_id)
    saved = await admin.create_checkpoint(match_id, state.summary.revision)
    result = await admin.wait_for_command(match_id, saved.command_id, timeout=60)
    assert result.status is CommandStatus.COMPLETED
    assert result.checkpoint_id
    await act(red, MoveCaptureAction(unit_id=infantry, path=()))
    await act(
        red,
        MoveAttackAction(
            unit_id=tank,
            path=coords([(7, 5)]),
            target=Coordinate(x=8, y=5),
        ),
    )
    return result.checkpoint_id


def battle_at(state):
    assert state.settled and state.observation
    battle = state.observation.game_state.battle.value
    assert battle is not None
    return battle


def board_scores(scenario, before, after):
    if scenario == "opening":
        return {
            "capture_units_produced": sum(
                unit.army_slot == 1 and unit.unit_type in CAPTURE_UNIT_TYPES for unit in after.units
            )
        }
    owned = any(
        (prop.x, prop.y, prop.owner_slot) == (*CAPTURE_TILE, 1) for prop in after.properties
    )
    capture_progress = (
        20
        if owned
        else max(
            (
                unit.capture_points
                for unit in after.units
                if unit.army_slot == 1
                and (unit.x, unit.y) == CAPTURE_TILE
                and 0 < unit.capture_points < 20
            ),
            default=0,
        )
    )

    def combat_balance(battle):
        return sum(
            unit.internal_health if unit.army_slot == 1 else -unit.internal_health
            for unit in battle.units
        )

    # Purchases add full-health units. Subtract those so they do not score as damage.
    old_slots = {(unit.army_slot, unit.reference) for unit in before.units}
    purchased_health = sum(
        unit.internal_health
        for unit in after.units
        if unit.army_slot == 1 and (unit.army_slot, unit.reference) not in old_slots
    )
    initial_capture = next(
        unit.capture_points
        for unit in before.units
        if unit.army_slot == 1 and (unit.x, unit.y) == CAPTURE_TILE
    )
    return {
        "capture_progress": capture_progress - initial_capture,
        "net_combat_hp": combat_balance(after) - combat_balance(before) - purchased_health,
    }


async def read_metrics(log, admin, match_id):
    usage = dict.fromkeys(("input", "cacheRead", "output"), 0)
    tool_calls = 0
    reply_bytes = []
    commands = set()
    failures = 0
    models = set()
    for line in log.read_bytes().splitlines():
        if not line.startswith(b"{"):
            continue
        event = json.loads(line)
        message = event.get("message", {})
        if event["type"] == "message_end" and message.get("role") == "assistant":
            for key in usage:
                usage[key] += message.get("usage", {}).get(key, 0)
            if message.get("model"):
                models.add(message["model"])
        if event["type"] == "tool_execution_start":
            tool_calls += 1
        if event["type"] == "message_end" and message.get("role") == "toolResult":
            parts = message.get("content", [])
            texts = [part["text"] for part in parts if part["type"] == "text"]
            reply_bytes.append(sum(len(value.encode()) for value in texts))
        if event["type"] == "tool_execution_end":
            name = event["toolName"].removeprefix("mcp__aw2__")
            result = event.get("result", {}).get("structuredContent") or {}
            if name == "play_action" or name not in OBSERVATION_TOOLS:
                failures += bool(event.get("isError") or result.get("isError"))
            body = result.get("structuredContent", result)
            if command_id := body.get("command", body).get("command_id"):
                commands.add(UUID(command_id))
    statuses = [await admin.command_status(match_id, identifier) for identifier in commands]
    return {
        "tool_calls": tool_calls,
        "reply_bytes": reply_bytes,
        "rejected_actions": failures
        + sum(item.status is CommandStatus.REJECTED for item in statuses),
        "rolled_back_actions": sum(item.status is CommandStatus.ROLLED_BACK for item in statuses),
        "tokens": usage,
        "models": sorted(models),
    }


async def verify_pi_tools(root, url, token, match_id, executable):
    extension = root / "verify-tools.ts"
    extension.write_text(
        """export default function(pi) {
          pi.on("session_start", () => {
            const timer = setInterval(() => {
              const activeTools = pi.getActiveTools();
              if (activeTools.length === 0) return;
              clearInterval(timer);
              console.error(JSON.stringify({activeTools}));
            }, 100);
          });
        }
        """
    )
    command, environment = prepare_pi(
        root / "tool-probe",
        url=url + "/mcp/",
        token=token,
        match_id=match_id,
        slot=SLOT,
        executable=executable,
        model=MODEL,
        prompt="Play AW2",
        mcp_profile="compact",
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        "--extension",
        str(extension),
        "--mode",
        "rpc",
        "--no-session",
        cwd=root / "tool-probe",
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stderr is not None
    try:
        async with asyncio.timeout(60):
            while line := await process.stderr.readline():
                if line.startswith(b'{"activeTools":'):
                    tools = json.loads(line)["activeTools"]
                    break
            else:
                pytest.fail("Pi exited before listing its active tools")
            process.stdin.close()
            assert await process.wait() == 0
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert sorted(tools) == sorted(f"mcp__aw2__{tool}" for tool in COMPACT_AI_TOOLS)


def test_benchmark_ai_mcp_profiles(tmp_path):
    rom = Path(os.environ["AW2_ROM_PATH"]).expanduser()
    pi = os.environ.get("AW2_BENCHMARK_PI_BIN", "pi")
    assert rom.is_file()

    async def compare():
        operator = SecretStr(token_urlsafe(32))
        tokens = (SecretStr(token_urlsafe(32)), SecretStr(token_urlsafe(32)))
        operator_file = tmp_path / "operator-token"
        operator_file.touch(mode=0o600)
        operator_file.write_text(operator.get_secret_value())
        async with (
            server(tmp_path, "headless", rom) as url,
            AsyncAW2Client(url, credential=operator) as admin,
            AsyncAW2Client(url, credential=tokens[0]) as red,
            AsyncAW2Client(url, credential=tokens[1]) as blue,
        ):
            match_id = (await admin.create_match()).match_id
            for slot, player in ((PlayerSlot.SLOT_1, red), (PlayerSlot.SLOT_2, blue)):
                invitation = SecretStr(token_urlsafe(32))
                await admin.invite(match_id, slot, invitation)
                await player.join(match_id, slot, invitation, slot.value)
            started = await admin.start(match_id, 0)
            opening = await admin.wait_for_command(match_id, started.command_id, timeout=200)
            assert opening.status is CommandStatus.COMPLETED and opening.checkpoint_id
            await verify_pi_tools(tmp_path, url, tokens[0].get_secret_value(), match_id, pi)
            midgame = await prepare_midgame(red, blue, admin, match_id)
            for scenario, checkpoint in (("opening", opening.checkpoint_id), ("midgame", midgame)):
                for repeat, order in enumerate(
                    (("standard", "compact"), ("compact", "standard")), start=1
                ):
                    for profile in order:
                        before = battle_at(await restore(admin, match_id, checkpoint))
                        run = tmp_path / f"{scenario}-{repeat}-{profile}"
                        run.mkdir(mode=0o700)
                        began = perf_counter()
                        error = None
                        budget = TurnBudget(limit=1)
                        try:
                            await ai_player(
                                slot=SLOT,
                                token=tokens[0].get_secret_value(),
                                match_id=match_id,
                                base_url=url,
                                run_dir=run,
                                model=MODEL,
                                executable=pi,
                                thinking="medium",
                                timeout=600,
                                budget=budget,
                                stop=asyncio.Event(),
                                attempts=1,
                                mcp_profile=profile,
                            )
                        except PlayError as caught:
                            error = str(caught).split(";")[0]
                        elapsed = round(perf_counter() - began, 2)
                        after = battle_at(await admin.state(match_id))
                        metrics = await read_metrics(
                            run / SLOT.value / "turn-1.jsonl", admin, match_id
                        )
                        result = {
                            "scenario": scenario,
                            "repeat": repeat,
                            "profile": profile,
                            "duration_seconds": elapsed,
                            "ended_turn": before.active_player_slot != after.active_player_slot,
                            "error": error,
                            **board_scores(scenario, before, after),
                            **metrics,
                        }
                        with (tmp_path / "results.jsonl").open("a") as output:
                            output.write(json.dumps(result) + "\n")
                        print(
                            json.dumps(
                                {
                                    key: value
                                    for key, value in result.items()
                                    if key != "reply_bytes"
                                }
                            ),
                            flush=True,
                        )
                        assert metrics["models"] == [MODEL.split("/", 1)[1]], (
                            "Pi did not stream the configured model; inspect the private turn log"
                        )
                        assert sum(metrics["tokens"].values()) > 0, (
                            "Pi completed no paid inference; inspect the private turn log"
                        )

    asyncio.run(compare())
