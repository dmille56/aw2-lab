"""Opt-in live Move and Capture checks using supplied playable checkpoints."""

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
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    Coordinate,
    MatchLifecycle,
    MoveCaptureAction,
    PlayerSlot,
)
from aw2_lab.match_observation import ActionReadiness, IdentityStatus, MatchObservationTracker
from aw2_lab.move_capture_executor import MoveCaptureActionExecutor
from aw2_lab.state_decoder import capture_game_state

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MOVE_CAPTURE_TESTS") != "1",
    reason="set AW2_RUN_MOVE_CAPTURE_TESTS=1 and the AW2_MOVE_CAPTURE_* checkpoint variables",
)


@pytest.mark.parametrize("scenario", ("partial", "complete", "hq_victory"))
def test_move_capture_against_playable_checkpoint(
    scenario: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"AW2_MOVE_CAPTURE_{scenario.upper()}"
    checkpoint_value = os.environ.get(f"{prefix}_CHECKPOINT")
    if not checkpoint_value:
        pytest.skip(f"set {prefix}_CHECKPOINT to a playable capture checkpoint")
    rom = Path(os.environ.get("AW2_ROM_PATH", ""))
    checkpoint = Path(checkpoint_value)
    assert rom.is_file(), "AW2_ROM_PATH must name the supported local ROM"
    assert checkpoint.is_file(), f"{prefix}_CHECKPOINT must name a playable savestate"
    unit_reference = int(os.environ[f"{prefix}_UNIT_REFERENCE"])
    raw_path = json.loads(os.environ.get(f"{prefix}_PATH", "[]"))
    path = tuple((int(point[0]), int(point[1])) for point in raw_path)
    mode = EmulatorMode(os.environ.get("AW2_MOVE_CAPTURE_MODE", EmulatorMode.HEADLESS.value))

    config = tmp_path / "config" / "mgba"
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
            unit = next(item for item in battle.units if item.reference == unit_reference)
            assert unit.army_slot == battle.active_player_slot
            destination = path[-1] if path else (unit.x, unit.y)
            prop = next(item for item in battle.properties if (item.x, item.y) == destination)
            assert prop.owner_slot != unit.army_slot

            tracker = MatchObservationTracker(uuid4())
            observation = tracker.commit_boundary(initial)
            unit_id = next(
                item.identity_id
                for item in observation.unit_identities
                if item.reference == unit.reference
            )
            request = CommandRequest(
                match_id=observation.match_id,
                player_slot=(
                    PlayerSlot.SLOT_1 if battle.active_player_slot == 1 else PlayerSlot.SLOT_2
                ),
                credential=SecretStr("x" * 32),
                request_id=uuid4(),
                expected_revision=observation.revision,
                action=MoveCaptureAction(
                    unit_id=unit_id,
                    path=tuple(Coordinate(x=x, y=y) for x, y in path),
                ),
            )
            outcome = await MoveCaptureActionExecutor(
                ActionNavigator(bridge, observe), tracker
            ).execute(request, observation)
            result = outcome.observation
            assert result is not None
            evidence = {
                "scenario": scenario,
                "mode": mode.value,
                "build_identity": launcher.build_identity,
                "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "frames": [initial.frame, result.game_state.frame],
                "lifecycle": outcome.lifecycle.value,
                "phase": result.game_state.lifecycle.phase.value,
                "unit_reference": unit.reference,
                "unit_identity": unit_id,
                "property": [prop.x, prop.y],
                "property_owner": [prop.owner_slot],
                "capture_points": [unit.capture_points],
            }
            if scenario == "hq_victory":
                assert outcome.lifecycle is MatchLifecycle.FINISHED
                assert result.identity_status is IdentityStatus.UNAVAILABLE
                assert result.game_state.battle.value is None
                assert result.game_state.lifecycle.phase in {
                    LifecyclePhase.RESULT_SEQUENCE,
                    LifecyclePhase.VICTORY_PRESENTATION,
                    LifecyclePhase.DEFEAT_PRESENTATION,
                    LifecyclePhase.RESULT_SUMMARY,
                    LifecyclePhase.SAVE_PROGRESS_PROMPT,
                }
            else:
                assert outcome.lifecycle is MatchLifecycle.PLAYABLE
                assert result.action_readiness is ActionReadiness.READY
                final_battle = result.game_state.battle.value
                assert final_battle is not None
                final_unit = next(
                    item for item in final_battle.units if item.reference == unit.reference
                )
                final_property = next(
                    item for item in final_battle.properties if (item.x, item.y) == destination
                )
                assert final_unit.used_this_turn
                assert (final_unit.x, final_unit.y) == destination
                assert any(
                    item.reference == unit.reference and item.identity_id == unit_id
                    for item in result.unit_identities
                )
                evidence["property_owner"].append(final_property.owner_slot)
                evidence["capture_points"].append(final_unit.capture_points)
                if scenario == "partial":
                    assert final_property.owner_slot == prop.owner_slot
                    assert final_unit.capture_points > unit.capture_points
                else:
                    assert final_property.owner_slot == unit.army_slot
                    assert final_unit.capture_points == 0
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
