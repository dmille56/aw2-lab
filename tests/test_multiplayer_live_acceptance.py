"""Opt-in mGBA acceptance of all COs in both player slots and launch modes."""

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
from aw2_lab.api_contract import default_players
from aw2_lab.cold_boot import boot_fixed_versus_match
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.end_turn_executor import EndTurnActionExecutor
from aw2_lab.map_catalog import MAPS_BY_ID
from aw2_lab.match_contract import (
    CO_ID_VALUES,
    CommandRequest,
    EndTurnAction,
    MatchLifecycle,
    PlayerSlot,
    SurrenderAction,
)
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.surrender_executor import SurrenderActionExecutor

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_MULTIPLAYER_TESTS") != "1",
    reason="set AW2_RUN_MULTIPLAYER_TESTS=1 and AW2_ROM_PATH for live CO selection",
)


@pytest.mark.parametrize("mode", ("headless", "windowed"))
@pytest.mark.parametrize(
    "map_id",
    ("bean_island", "pyramid_cape", "four_corners", "delta_heights", "coil_range", "stamp_islands"),
)
def test_live_multiplayer_setup(mode: str, map_id: str, tmp_path: Path) -> None:
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    assert rom.is_file(), "AW2_ROM_PATH must name the supported ROM"
    if mode == "windowed" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("windowed acceptance requires a display")
    co_ids = tuple(p.co_id for p in default_players(MAPS_BY_ID[map_id].player_count))
    team_ids = (0, 1) if len(co_ids) == 2 else (0, 1, 1) if len(co_ids) == 3 else (0, 0, 1, 1)
    source_save = rom.with_suffix(".sav")
    source_hash = (
        hashlib.sha256(source_save.read_bytes()).hexdigest() if source_save.is_file() else None
    )

    async def check() -> None:
        launcher = EmulatorLauncher(
            EmulatorSettings(rom_path=rom, mode=EmulatorMode(mode), suppress_emulator_output=True),
            isolate_saves=True,
        )
        try:
            await launcher.start()
            bridge = launcher.bridge
            assert bridge is not None
            result = await boot_fixed_versus_match(
                bridge,
                rom_path=rom,
                co_ids=co_ids,
                team_ids=team_ids,
                map_id=map_id,
                save_mode="existing",
            )
            battle = result.game_state.battle.value
            assert battle is not None
            actual = {player.slot: player.co_id for player in battle.players}
            battle_ids = {
                0: 0,
                1: 1,
                2: 2,
                3: 4,
                4: 15,
                5: 3,
                6: 5,
                7: 16,
                8: 6,
                9: 7,
                10: 18,
                11: 8,
                12: 9,
                13: 17,
                14: 11,
                15: 12,
                16: 13,
                17: 14,
                18: 10,
            }
            expected = {
                slot: battle_ids[CO_ID_VALUES.index(co_id)] for slot, co_id in enumerate(co_ids, 1)
            }
            assert actual == expected
            assert tuple(p.team_id for p in battle.players) == team_ids
            assert all(p.control_type == 1 for p in battle.players)
            screenshot = await bridge.screenshot()
            (tmp_path / "ready.png").write_bytes(screenshot)
            if map_id in ("pyramid_cape", "four_corners"):
                tracker = MatchObservationTracker(uuid4())
                observation = tracker.commit_boundary(result.game_state)

                async def observe():
                    return await capture_game_state(bridge, rom_path=rom)

                executor = EndTurnActionExecutor(ActionNavigator(bridge, observe), tracker)
                for index in range(len(co_ids)):
                    request = CommandRequest(
                        match_id=observation.match_id,
                        player_slot=PlayerSlot(f"slot_{index + 1}"),
                        credential=SecretStr("x" * 43),
                        request_id=uuid4(),
                        expected_revision=observation.revision,
                        action=EndTurnAction(),
                    )
                    outcome = await executor.execute(request, observation)
                    observation = outcome.observation
                    assert (
                        observation.game_state.battle.value.active_player_slot
                        == (index + 1) % len(co_ids) + 1
                    )
                assert observation.game_state.battle.value.day == 2
                if map_id == "four_corners":
                    request = CommandRequest(
                        match_id=observation.match_id,
                        player_slot=PlayerSlot.SLOT_1,
                        credential=SecretStr("x" * 43),
                        request_id=uuid4(),
                        expected_revision=observation.revision,
                        action=SurrenderAction(),
                    )
                    yielded = await SurrenderActionExecutor(executor.navigator, tracker).execute(
                        request, observation
                    )
                    assert yielded.lifecycle is MatchLifecycle.PLAYABLE
                    assert yielded.observation.game_state.battle.value.active_player_slot == 2
                    observation = yielded.observation
                    for current, following in ((2, 3), (3, 4), (4, 2)):
                        request = CommandRequest(
                            match_id=observation.match_id,
                            player_slot=PlayerSlot(f"slot_{current}"),
                            credential=SecretStr("x" * 43),
                            request_id=uuid4(),
                            expected_revision=observation.revision,
                            action=EndTurnAction(),
                        )
                        observation = (await executor.execute(request, observation)).observation
                        assert observation.game_state.battle.value.active_player_slot == following
                    assert observation.game_state.battle.value.day == 3

            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "co_ids": co_ids,
                        "map_id": map_id,
                        "team_ids": team_ids,
                        "rom_sha256": select_rom_profile(rom).sha256,
                        "build": launcher.build_identity,
                        "mode": mode,
                        "frame": result.game_state.frame,
                        "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
                        "source_save_sha256": source_hash,
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            await launcher.stop()

    asyncio.run(check())
    if source_hash is not None:
        assert hashlib.sha256(source_save.read_bytes()).hexdigest() == source_hash
