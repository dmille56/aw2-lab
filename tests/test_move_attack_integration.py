"""Opt-in move/attack regressions using the external red-ready research checkpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.match_contract import (
    CommandRequest,
    Coordinate,
    MatchLifecycle,
    MoveAttackAction,
    PlayerSlot,
)
from aw2_lab.match_observation import ActionReadiness, IdentityStatus, MatchObservationTracker
from aw2_lab.move_attack_executor import MoveAttackActionExecutor
from aw2_lab.state_decoder import capture_game_state

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MOVE_ATTACK_TESTS") != "1",
    reason="set AW2_RUN_MOVE_ATTACK_TESTS=1, AW2_ROM_PATH, and AW2_MOVE_ATTACK_CHECKPOINT",
)


def _emulator_mode() -> EmulatorMode:
    value = os.environ.get("AW2_MOVE_ATTACK_MODE", EmulatorMode.HEADLESS.value)
    try:
        return EmulatorMode(value)
    except ValueError as error:
        raise ValueError("AW2_MOVE_ATTACK_MODE must be 'headless' or 'windowed'") from error


@pytest.mark.parametrize(
    ("start", "path", "target_position", "expected_outcome"),
    [
        ((1, 5), (), (1, 4), "survives"),
        ((1, 5), (), (2, 5), "survives"),
        ((0, 6), ((0, 5), (0, 4)), (1, 4), "survives"),
        ((4, 4), (), (3, 4), "destroyed"),
        ((10, 5), (), (10, 6), "terminal"),
    ],
    ids=(
        "default-target",
        "cycle-target",
        "move-before-attack",
        "attacker-destroyed",
        "final-enemy",
    ),
)
def test_move_attack_against_playable_units(
    start: tuple[int, int],
    path: tuple[tuple[int, int], ...],
    target_position: tuple[int, int],
    expected_outcome: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    checkpoint_variable = (
        "AW2_MOVE_ATTACK_TERMINAL_CHECKPOINT"
        if expected_outcome == "terminal"
        else "AW2_MOVE_ATTACK_CHECKPOINT"
    )
    if expected_outcome == "terminal" and not os.environ.get(checkpoint_variable):
        pytest.skip("set AW2_MOVE_ATTACK_TERMINAL_CHECKPOINT to a final-enemy ready state")
    checkpoint = Path(os.environ.get(checkpoint_variable, ""))
    assert rom.is_file(), "AW2_ROM_PATH must name the supported local ROM"
    assert checkpoint.is_file(), f"{checkpoint_variable} must name the case's playable checkpoint"
    config = tmp_path / "config" / "mgba"
    mode = _emulator_mode()
    config.mkdir(parents=True)
    saves = tmp_path / "saves"
    saves.mkdir()
    (config / "config.ini").write_text(
        f"[ports.{mode.value}]\nsavegamePath={saves}\nsavestatePath={saves}\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom.resolve(),
                mode=mode,
                headless_executable=os.environ.get("AW2_TEST_MGBA_HEADLESS", "mgba-headless"),
                bridge_script=Path(__file__).resolve().parents[1] / "lua" / "bridge.lua",
                suppress_emulator_output=True,
            )
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None
            await bridge.load_state(checkpoint.resolve())

            async def observe():
                return await capture_game_state(bridge, rom_path=rom)

            initial = await observe()
            battle = initial.battle.value
            assert battle is not None
            attacker = next(
                unit
                for unit in battle.units
                if (unit.x, unit.y) == start and unit.army_slot == battle.active_player_slot
            )
            target = next(
                unit
                for unit in battle.units
                if (unit.x, unit.y) == target_position
                and unit.army_slot != battle.active_player_slot
            )
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
            unit_id = next(
                item.identity_id
                for item in observation.unit_identities
                if item.reference == attacker.reference
            )
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=PlayerSlot.SLOT_1,
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=MoveAttackAction(
                    unit_id=unit_id,
                    path=tuple(Coordinate(x=x, y=y) for x, y in path),
                    target=Coordinate(x=target.x, y=target.y),
                ),
            )
            # Use production defaults: overly frequent combat polling used to
            # exhaust the wall timeout before the animation could finish.
            navigator = ActionNavigator(bridge, observe)
            outcome = await MoveAttackActionExecutor(navigator, tracker).execute(
                request, observation
            )
            result = outcome.observation
            assert result is not None
            assert result.revision == observation.revision + 1
            evidence = {
                "mode": mode.value,
                "build_identity": launcher.build_identity,
                "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "frames": [initial.frame, result.game_state.frame],
                "expected_outcome": expected_outcome,
                "lifecycle": outcome.lifecycle.value,
                "phase": result.game_state.lifecycle.phase.value,
                "co_effects_enabled": battle.co_effects_enabled.value,
                "fog_enabled": battle.fog_enabled.value,
                "attacker_reference": attacker.reference,
                "target_reference": target.reference,
            }
            if expected_outcome == "terminal":
                assert outcome.lifecycle is MatchLifecycle.FINISHED
                assert result.identity_status is IdentityStatus.UNAVAILABLE
                assert result.game_state.battle.value is None
            else:
                assert outcome.lifecycle is MatchLifecycle.PLAYABLE
                assert result.action_readiness is ActionReadiness.READY
                final_battle = result.game_state.battle.value
                assert final_battle is not None
                final_attacker = next(
                    (u for u in final_battle.units if u.reference == attacker.reference), None
                )
                if expected_outcome == "destroyed":
                    assert final_attacker is None
                    assert all(i.identity_id != unit_id for i in result.unit_identities)
                else:
                    assert final_attacker is not None
                    assert (final_attacker.x, final_attacker.y) == (path[-1] if path else start)
                    assert final_attacker.used_this_turn
                    assert any(
                        i.reference == attacker.reference and i.identity_id == unit_id
                        for i in result.unit_identities
                    )
                final_target = next(
                    (u for u in final_battle.units if u.reference == target.reference), None
                )
                assert final_target is None or final_target.internal_health < target.internal_health
                evidence["attacker_health"] = [
                    attacker.internal_health,
                    None if final_attacker is None else final_attacker.internal_health,
                ]
                evidence["target_health"] = [
                    target.internal_health,
                    None if final_target is None else final_target.internal_health,
                ]
                evidence["fuel"] = [
                    attacker.fuel,
                    None if final_attacker is None else final_attacker.fuel,
                ]
            (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            (tmp_path / "result.png").write_bytes(await bridge.screenshot())
            print(json.dumps(evidence))
        except Exception:
            if launcher.bridge is not None:
                (tmp_path / "failure.png").write_bytes(await launcher.bridge.screenshot())
                await launcher.bridge.save_state(tmp_path / "failure.ss0")
            raise
        finally:
            await launcher.stop()

    asyncio.run(check())
