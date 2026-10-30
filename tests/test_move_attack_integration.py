"""Opt-in move/attack regressions using the external red-ready research checkpoint."""

from __future__ import annotations

import asyncio
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
from aw2_lab.match_observation import ActionReadiness, MatchObservationTracker
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
    ("start", "path", "target_position"),
    [
        ((1, 5), (), (1, 4)),
        ((1, 5), (), (2, 5)),
        ((0, 6), ((0, 5), (0, 4)), (1, 4)),
    ],
    ids=("default-target", "cycle-target", "move-before-attack"),
)
def test_move_attack_against_playable_units(
    start: tuple[int, int],
    path: tuple[tuple[int, int], ...],
    target_position: tuple[int, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    checkpoint = Path(os.environ.get("AW2_MOVE_ATTACK_CHECKPOINT", ""))
    assert rom.is_file(), "AW2_ROM_PATH must name the supported local ROM"
    assert checkpoint.is_file(), "AW2_MOVE_ATTACK_CHECKPOINT must name red-ready.ss0"
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
            assert outcome.lifecycle is MatchLifecycle.PLAYABLE
            result = outcome.observation
            assert result is not None
            assert result.action_readiness is ActionReadiness.READY
            assert result.revision == observation.revision + 1
            final_battle = result.game_state.battle.value
            assert final_battle is not None
            final_attacker = next(
                unit for unit in final_battle.units if unit.reference == attacker.reference
            )
            assert (final_attacker.x, final_attacker.y) == (path[-1] if path else start)
            assert final_attacker.used_this_turn
            assert any(
                item.reference == attacker.reference and item.identity_id == unit_id
                for item in result.unit_identities
            )
            final_target = next(
                (unit for unit in final_battle.units if unit.reference == target.reference), None
            )
            assert final_target is None or final_target.internal_health < target.internal_health
            print(
                f"frames={initial.frame}->{result.game_state.frame} "
                f"attacker={final_attacker.reference}@{final_attacker.x},{final_attacker.y} "
                f"health={attacker.internal_health}->{final_attacker.internal_health} "
                f"target_health={target.internal_health}->"
                f"{None if final_target is None else final_target.internal_health}"
            )
        finally:
            await launcher.stop()

    asyncio.run(check())
