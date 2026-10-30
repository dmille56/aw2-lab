"""Opt-in live Move and Wait check against a supplied playable-unit checkpoint."""

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
    MoveWaitAction,
    PlayerSlot,
)
from aw2_lab.match_observation import ActionReadiness, MatchObservationTracker
from aw2_lab.move_wait_executor import MoveWaitActionExecutor
from aw2_lab.state_decoder import capture_game_state

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MOVE_WAIT_TESTS") != "1",
    reason="set AW2_RUN_MOVE_WAIT_TESTS=1, AW2_ROM_PATH, and AW2_MOVE_WAIT_CHECKPOINT",
)


def test_move_wait_against_playable_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    checkpoint = Path(os.environ.get("AW2_MOVE_WAIT_CHECKPOINT", ""))
    assert rom.is_file(), "AW2_ROM_PATH must name the supported local ROM"
    assert checkpoint.is_file(), "AW2_MOVE_WAIT_CHECKPOINT must name a playable savestate"
    config = tmp_path / "config" / "mgba"
    config.mkdir(parents=True)
    saves = tmp_path / "saves"
    saves.mkdir()
    (config / "config.ini").write_text(
        f"[ports.headless]\nsavegamePath={saves}\nsavestatePath={saves}\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(
                rom_path=rom.resolve(),
                mode=EmulatorMode.HEADLESS,
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

            initial_state = await observe()
            battle = initial_state.battle.value
            assert battle is not None
            assert battle.active_player_slot == 1
            unit = next(
                item
                for item in battle.units
                if item.reference == 1
                and item.army_slot == battle.active_player_slot
                and not item.used_this_turn
            )
            assert (unit.unit_type, unit.x, unit.y) == (1, 11, 2)
            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial_state)
            unit_id = next(
                item.identity_id
                for item in observation.unit_identities
                if item.reference == unit.reference
            )
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=PlayerSlot.SLOT_1,
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=MoveWaitAction(
                    unit_id=unit_id,
                    path=(Coordinate(x=12, y=2),),
                ),
            )
            outcome = await MoveWaitActionExecutor(
                ActionNavigator(bridge, observe), tracker
            ).execute(request, observation)
            assert outcome.lifecycle is MatchLifecycle.PLAYABLE
            result = outcome.observation
            assert result is not None and result.action_readiness is ActionReadiness.READY
            final_battle = result.game_state.battle.value
            assert final_battle is not None
            moved = next(item for item in final_battle.units if item.reference == unit.reference)
            assert (moved.x, moved.y) == (12, 2)
            assert moved.used_this_turn
            final_identity = next(
                item for item in result.unit_identities if item.reference == unit.reference
            )
            assert final_identity.identity_id == unit_id
        finally:
            await launcher.stop()

    asyncio.run(check())
