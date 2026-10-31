"""Decoder boundary checks using coherent synthetic RAM, with no game artifacts."""

import asyncio
import json
from dataclasses import replace
from struct import pack_into

import pytest
from test_state_validation import SnapshotBridge, snapshot
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture

from aw2_lab import state_decoder
from aw2_lab.bridge import BridgeError
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.rom_profile import UnsupportedRomError
from aw2_lab.state_decoder import capture_game_state, decode_snapshot
from aw2_lab.state_model import ObservedValue, ValueStatus, Weather
from aw2_lab.ui_state import MenuFamily


def test_live_decoder_preserves_packed_fields_ownership_and_json_contract(memory) -> None:
    _, raw, control = memory
    raw[0x22690] = 11  # Md Tank, including health bit 7 carried by ammunition.
    raw[0x22691] = 1
    pack_into("<H", raw, 0x22694, (9 << 7) | 37)
    raw[0x22696] = 0x80 | 45
    raw[0x2269C:0x226A8] = bytes((1, 1, 1, 1, 65, 10 << 3, 50, 0, 0, 0, 0, 0))
    raw[0x22992:0x22994] = bytes((1, 0))
    pack_into("<I", raw, 0x232C0, 12345)
    pack_into("<i", raw, 0x232E0, 32400)
    raw[0x232E5] = 10
    control[0x3FEC] = 2

    state = decode_snapshot(snapshot(memory))
    assert state.battle.status is ValueStatus.AVAILABLE
    battle = state.battle.value
    assert battle is not None
    assert (battle.day, battle.active_player_slot) == (1, 1)
    assert battle.weather.value is Weather.RAIN
    assert (battle.map.width, battle.map.height) == (2, 2)
    assert [(t.x, t.y) for t in battle.map.tiles] == [(0, 0), (1, 0), (0, 1), (1, 1)]
    assert [(p.terrain_class, p.owner_slot) for p in battle.properties] == [(6, 1), (6, 2)]
    assert battle.players[0].funds == 12345
    assert battle.players[0].power_meter == ObservedValue(ValueStatus.AVAILABLE, 32400)
    assert battle.players[0].power_use_counter == ObservedValue(ValueStatus.AVAILABLE, 10)
    tank, infantry, blue = battle.units
    assert (tank.internal_health, tank.ammo, tank.fuel, tank.used_this_turn) == (37, 9, 45, True)
    assert (infantry.internal_health, infantry.ammo, infantry.capture_points) == (65, 0, 10)
    assert (blue.reference, blue.army_slot, blue.unit_slot) == (65, 2, 1)
    encoded = json.loads(json.dumps(state.to_dict()))
    assert encoded["schema_version"] == 4
    assert encoded["frame"] == state.validation.frame == state.ui.frame
    assert encoded["context"]["rom_profile"]["sha256"] == memory[0].profile.sha256
    assert encoded["battle"]["value"]["weather"] == {
        "status": "available",
        "value": "rain",
        "reasons": [],
    }
    assert encoded["battle"]["value"]["players"][0]["power_meter"] == {
        "status": "available",
        "value": 32400,
        "reasons": [],
    }


@pytest.mark.parametrize(
    ("meter", "counter", "meter_status", "counter_status"),
    [
        (0, 0, ValueStatus.AVAILABLE, ValueStatus.AVAILABLE),
        (32400, 10, ValueStatus.AVAILABLE, ValueStatus.AVAILABLE),
        (-1, 10, ValueStatus.UNKNOWN, ValueStatus.AVAILABLE),
        (32400, 11, ValueStatus.AVAILABLE, ValueStatus.UNKNOWN),
    ],
)
def test_player_power_observations_preserve_unverified_ranges(
    memory, meter, counter, meter_status, counter_status
) -> None:
    raw = memory[1]
    pack_into("<i", raw, 0x232E0, meter)
    raw[0x232E5] = counter

    battle = decode_snapshot(snapshot(memory)).battle.value
    assert battle is not None
    player = battle.players[0]
    assert player.power_meter.status is meter_status
    assert player.power_meter.value == (meter if meter_status is ValueStatus.AVAILABLE else None)
    assert bool(player.power_meter.reasons) is (meter_status is ValueStatus.UNKNOWN)
    assert player.power_use_counter.status is counter_status
    assert player.power_use_counter.value == (
        counter if counter_status is ValueStatus.AVAILABLE else None
    )
    assert bool(player.power_use_counter.reasons) is (counter_status is ValueStatus.UNKNOWN)


@pytest.mark.parametrize(
    "context", ["menu", "delete", "ai", "entry", "combat", "power", "result", "unknown"]
)
def test_retained_battle_memory_is_never_published_outside_live_control(memory, context) -> None:
    _, raw, control = memory
    match context:
        case "menu":
            control[0x30F0] = 1
        case "delete":
            pack_into("<H", control, 0x3334, 2)
        case "ai":
            pack_into("<H", control, 0x32D8, 14)
        case "entry":
            pack_into("<I", raw, 0xD610, 0x084892C4)
        case "combat":
            pack_into("<I", raw, 0xD610, 0x0849A9F8)
            pack_into("<I", raw, 0xD67C, 0x0849FEF8)
        case "power":
            pack_into("<I", raw, 0xD610, 0x0849D77C)
        case "result":
            pack_into("<I", raw, 0xD610, 0x084C327C)
        case "unknown":
            pack_into("<I", control, 0x40D0, 0)
    state = decode_snapshot(snapshot(memory))
    assert state.battle.status is ValueStatus.UNAVAILABLE
    assert state.battle.value is None
    assert state.battle.reasons
    if context == "delete":
        assert state.ui.menu.family is MenuFamily.UNRESOLVED
        assert state.ui.menu.unrecognized.controller.input_state == 2


@pytest.mark.parametrize("corruption", ["rows", "property", "cargo", "unit_type", "dimensions"])
def test_decoder_does_not_follow_invalid_or_unsupported_structures(memory, corruption) -> None:
    _, raw, control = memory
    match corruption:
        case "rows":
            pack_into("<H", raw, 0x225CA, 0xFFFF)
        case "property":
            control[0x3151] = 255
        case "cargo":
            raw[0x22690] = 7
            raw[0x22697] = 65  # Foreign-army reference.
        case "unit_type":
            raw[0x22690] = 255
        case "dimensions":
            pack_into("<H", raw, 0x1E450, 0xFFFF)
    state = decode_snapshot(snapshot(memory))
    assert state.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
    assert state.battle.value is None
    expected = (
        ValueStatus.UNKNOWN
        if corruption in {"unit_type", "dimensions"}
        else ValueStatus.UNAVAILABLE
    )
    assert state.battle.status is expected


def test_unknown_weather_does_not_invent_a_weather_or_discard_other_verified_fields(memory) -> None:
    memory[2][0x3FEC] = 255
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    assert battle.weather.status is ValueStatus.UNKNOWN
    assert battle.weather.value is None
    assert "255" in battle.weather.reasons[0]
    assert len(battle.units) == 2


def test_global_cargo_references_and_stale_empty_records_remain_distinct(memory) -> None:
    raw = memory[1]
    raw[0x22990] = 7
    raw[0x22991] = 0x10
    raw[0x22997] = 66
    raw[0x2299C:0x229A8] = bytes((1, 9, 0, 0, 100, 0, 99, 0, 0, 0, 0, 0))
    raw[0x2269C:0x226A8] = bytes((0, 255, 255, 255, 0, 255, 255, 255, 255, 255, 255, 255))
    state = decode_snapshot(snapshot(memory))
    battle = state.battle.value
    assert battle is not None
    assert [unit.reference for unit in battle.units] == [1, 65, 66]
    transport, passenger = battle.units[1:]
    assert transport.cargo_references == (66,)
    assert passenger.embarked
    assert passenger.used_this_turn
    assert (transport.x, transport.y) != (passenger.x, passenger.y)


class CaptureBridge(SnapshotBridge):
    def __init__(self, source, *, drift=False, truncate=False):
        super().__init__(source, drift=drift, truncate=truncate)
        self.frame_requests = []

    async def advance_frames(self, frames: int) -> int:
        self.frame_requests.append(frames)
        return await super().advance_frames(frames)


def test_capture_decodes_exact_frame_without_advancing(monkeypatch, memory, tmp_path) -> None:
    monkeypatch.setattr(state_decoder, "load_battle_layout", lambda _: memory[0])
    bridge = CaptureBridge(snapshot(memory))
    state = asyncio.run(capture_game_state(bridge, rom_path=tmp_path / "unused"))
    assert state.frame == 123
    assert state.battle.status is ValueStatus.AVAILABLE
    assert bridge.frame_requests == [0, 0]
    assert bridge.reads == (0x40000 + 0x8000) // 4096


@pytest.mark.parametrize("failure", ["drift", "final_drift", "truncated"])
def test_capture_publishes_nothing_on_incoherent_or_incomplete_ram(
    monkeypatch, memory, tmp_path, failure
) -> None:
    monkeypatch.setattr(state_decoder, "load_battle_layout", lambda _: memory[0])
    bridge = CaptureBridge(
        snapshot(memory), drift=failure == "drift", truncate=failure == "truncated"
    )
    bridge.final_drift = failure == "final_drift"
    with pytest.raises(BridgeError):
        asyncio.run(capture_game_state(bridge, rom_path=tmp_path / "unused"))
    assert set(bridge.frame_requests) == {0}


def test_bad_rom_fails_before_contacting_emulator(memory, tmp_path) -> None:
    path = tmp_path / "unsupported.gba"
    path.write_bytes(b"not a supported ROM")
    bridge = CaptureBridge(snapshot(memory))
    with pytest.raises(UnsupportedRomError):
        asyncio.run(capture_game_state(bridge, rom_path=path))
    assert bridge.frame_requests == []
    assert bridge.reads == 0


def test_state_contract_rejects_old_schema_cross_frame_and_absent_values(memory) -> None:
    state = decode_snapshot(snapshot(memory))
    with pytest.raises(ValueError, match="schema"):
        replace(state, schema_version=1)
    with pytest.raises(ValueError, match="same emulator frame"):
        replace(state, frame=state.frame + 1)
    with pytest.raises(ValueError, match="requires a value"):
        ObservedValue(ValueStatus.AVAILABLE, None)
    with pytest.raises(ValueError, match="requires reasons"):
        ObservedValue(ValueStatus.UNKNOWN, None)
    assert ObservedValue(ValueStatus.AVAILABLE, ()).value == ()


def test_process_evidence_survives_unrecognized_ui_without_publishing_data(memory) -> None:
    raw = memory[1]
    pack_into("<I", raw, 0xD610, 0xDEADBEEF)
    pack_into("<I", raw, 0xD67C, 0xDEADBEEF)
    state = decode_snapshot(snapshot(memory))
    assert state.battle.value is None
    assert state.ui.menu.unrecognized is not None
    assert state.ui.menu.unrecognized.lifecycle.active_process_scripts == (0xDEADBEEF, 0xDEADBEEF)


@pytest.mark.parametrize("raw", [0, 1, 255])
def test_rule_options_are_observed_without_assuming_unknown_encodings(memory, raw) -> None:
    _, _, iwram = memory
    iwram[0x3FC8] = iwram[0x3FCD] = raw
    battle = decode_snapshot(snapshot(memory)).battle.value
    assert battle is not None
    if raw in (0, 1):
        assert battle.co_effects_enabled == ObservedValue(ValueStatus.AVAILABLE, raw == 1)
        assert battle.fog_enabled == ObservedValue(ValueStatus.AVAILABLE, raw == 1)
    else:
        assert battle.co_effects_enabled.status is ValueStatus.UNKNOWN
        assert battle.fog_enabled.status is ValueStatus.UNKNOWN
