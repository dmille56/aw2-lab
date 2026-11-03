"""Debug authorization and invalidation use the real controller/runtime composition."""

from uuid import UUID, uuid4

import pytest
from test_authorization import token
from test_http_api import client_for, headers
from test_http_gameplay_checkpoints import setup
from test_match_controller import run_async_test
from test_state_validation import memory as memory  # noqa: PLC0414

from aw2_lab.debug_api import require_ram
from aw2_lab.match_controller import MatchControllerError


def test_debug_ram_regions_reject_crossing_and_non_ram():
    require_ram(0x02000000, 4096)
    require_ram(0x03007FFF, 1)
    for address, length in ((0, 1), (0x0203FFFF, 2), (0x03008000, 1), (0x08000000, 1)):
        with pytest.raises(MatchControllerError):
            require_ram(address, length)


@run_async_test
async def test_debug_reset_requires_opt_in_and_invalidates_gameplay(memory, tmp_path, monkeypatch):
    app, runtime, public, match_id, _, bridge = await setup(memory, tmp_path, monkeypatch)
    app.state.playable_runtime = runtime
    path = f"/v1/matches/{match_id}/debug/reset"
    body = {"request_id": str(uuid4()), "expected_revision": 1}
    try:
        async with client_for(app) as client:
            disabled = await client.post(path, headers=headers(), json=body)
            assert disabled.status_code == 422
            public.authorization.debug_enabled = True
            denied = await client.post(path, headers=headers("p"), json=body)
            assert denied.status_code == 403
            accepted = await client.post(path, headers=headers(), json=body)
            assert accepted.status_code == 202, accepted.text
            result = await runtime.controller.wait_for_command(
                match_id, UUID(accepted.json()["command_id"]), timeout=2
            )
            assert result.status.value == "recovery_required"
            state = await public.state(public.authenticate(token("o")), match_id)
            assert state.summary.revision == 2
            assert state.observation.identity_status.value == "unavailable"
            assert state.observation.game_state.battle.value is None
            retry = await client.post(path, headers=headers(), json=body)
            assert retry.json()["command_id"] == accepted.json()["command_id"]
            assert bridge.resets == 2  # Start and this debug reset; retry does not reset again.
    finally:
        await runtime.controller.stop()
