"""Opt-in real-application startup, dispatch, checkpoint, and restore check."""

import asyncio
import os
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.api import app as app_module
from aw2_lab.api_contract import (
    VERIFIED_CONFIGURATION,
    CreateMatchRequest,
    GameplayCommandRequest,
    IssueInvitationRequest,
    JoinSlotRequest,
    StartMatchRequest,
)
from aw2_lab.emulator import EmulatorMode, EmulatorSettings
from aw2_lab.match_contract import CommandStatus, PlayerSlot

pytestmark = pytest.mark.skipif(
    os.environ.get("AW2_RUN_RUNTIME_TESTS") != "1",
    reason="set AW2_RUN_RUNTIME_TESTS=1 and AW2_ROM_PATH for live runtime checks",
)


@pytest.mark.parametrize(
    "map_id",
    os.environ.get(
        "AW2_RUNTIME_MAP_IDS", os.environ.get("AW2_RUNTIME_MAP_ID", "bean_island")
    ).split(","),
)
def test_playable_runtime_start_turn_restore_and_continue(tmp_path, monkeypatch, map_id):
    rom = Path(os.environ.get("AW2_ROM_PATH", "")).expanduser()
    if not rom.is_file():
        pytest.fail("AW2_ROM_PATH must name a supported local ROM")
    mode = EmulatorMode(os.environ.get("AW2_RUNTIME_MODE", "headless"))
    if mode is EmulatorMode.WINDOWED and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("windowed mode requires a display")

    secret = SecretStr(token_urlsafe(32))
    secret_file = tmp_path / "operator-token"
    secret_file.write_text(secret.get_secret_value())
    secret_file.chmod(0o600)

    async def check():
        application = app_module.create_app(
            settings=EmulatorSettings(
                rom_path=rom.resolve(), mode=mode, suppress_emulator_output=True
            ),
            storage_root=tmp_path / "storage",
            operator_secret_file=secret_file,
        )
        async with application.router.lifespan_context(application):
            public = application.state.authorized_matches
            operator = public.authenticate(secret)
            summary = await public.create(
                operator,
                CreateMatchRequest(
                    request_id=uuid4(),
                    configuration=VERIFIED_CONFIGURATION.model_copy(update={"map_id": map_id}),
                ),
            )
            players = []
            for slot in tuple(PlayerSlot)[:2]:
                invitation, credential = SecretStr(token_urlsafe(32)), SecretStr(token_urlsafe(32))
                await public.invite(
                    operator,
                    summary.match_id,
                    slot,
                    IssueInvitationRequest(request_id=uuid4(), invitation_token=invitation),
                )
                await public.join(
                    summary.match_id,
                    slot,
                    credential,
                    JoinSlotRequest(
                        request_id=uuid4(), display_name=slot.value, invitation_token=invitation
                    ),
                )
                players.append(public.authenticate(credential))
            start = await public.start(
                operator,
                summary.match_id,
                StartMatchRequest(request_id=uuid4(), expected_revision=0),
            )
            result = await public.wait_for_command(
                operator, summary.match_id, start.command_id, timeout=190
            )
            assert result.status is CommandStatus.COMPLETED, result.error
            assert result.resulting_revision == 1 and result.checkpoint_id is not None
            initial = await public.state(operator, summary.match_id)
            assert initial.summary.configuration.map_id == map_id
            manifest, _blob = application.state.playable_runtime.store.load(result.checkpoint_id)
            assert manifest.match.configuration.map_id == map_id
            runtime = application.state.playable_runtime
            for expected_slot, player in ((2, players[0]), (1, players[1])):
                before = await public.state(operator, summary.match_id)
                command = await public.submit(
                    player,
                    summary.match_id,
                    GameplayCommandRequest(
                        request_id=uuid4(),
                        expected_revision=before.summary.revision,
                        action={"kind": "end_turn"},
                    ),
                )
                result = await public.wait_for_command(
                    operator, summary.match_id, command.command_id, timeout=90
                )
                assert result.status is CommandStatus.COMPLETED, result.error
                after = await public.state(operator, summary.match_id)
                assert after.observation.game_state.battle.value.active_player_slot == expected_slot
                assert runtime.store.current().command_result == result
                if expected_slot == 2:
                    tracker = runtime.checkpoints.session.tracker
                    restore = await runtime.checkpoints.restore(
                        summary.match_id,
                        result.checkpoint_id,
                        operator,
                        request_id=uuid4(),
                        expected_revision=after.summary.revision,
                    )
                    restored = await public.wait_for_command(
                        operator, summary.match_id, restore.command_id, timeout=90
                    )
                    assert restored.status is CommandStatus.COMPLETED, restored.error
                    assert runtime.checkpoints.session.tracker is not tracker
                    assert (
                        await public.state(operator, summary.match_id)
                    ).summary.configuration.map_id == map_id
            assert initial.observation.game_state.battle.value.day == 1
            assert after.observation.game_state.battle.value.day == 2

    asyncio.run(check())
