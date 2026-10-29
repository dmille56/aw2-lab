"""Synthetic memory tests for unavailable/stale data and bounded table validation."""

import asyncio
from dataclasses import replace
from struct import pack_into

import pytest

from aw2_lab.bridge import BridgeError, LuaBridgeClient, MemorySnapshot
from aw2_lab.lifecycle import (
    ANIMATION_CALLBACKS,
    BATTLE_CALLBACKS,
    SCREEN_CALLBACKS,
    LifecyclePhase,
)
from aw2_lab.rom_profile import AW2_US_REVISION_0, UnsupportedRomError
from aw2_lab.state_validation import (
    BattleLayout,
    BattleMemorySnapshot,
    BattleStructure,
    ValidationStatus,
    capture_battle_snapshot,
    load_battle_layout,
    validate_battle_snapshot,
)
from aw2_lab.ui_state import CursorStatus, MenuFamily, MenuItem, observe_map_cursor, observe_menu


@pytest.fixture
def memory() -> tuple[BattleLayout, bytearray, bytearray]:
    lookup = bytearray(1024)
    lookup[1:6] = bytes([1, 6, 0x26, 0x46, 9])
    layout = BattleLayout(AW2_US_REVISION_0, 0x0201E450, 0x02022684, 0x02023284, bytes(lookup))
    ewram, iwram = bytearray(0x40000), bytearray(0x8000)
    pack_into("<HH", ewram, 0x1E450, 2, 2)
    pack_into("<HH", ewram, 0x225CA, 0, 2)
    pack_into("<4H", ewram, 0x1EE72, 3, 1, 1, 4)
    ewram[0x1F882:0x1F886] = bytes([0x26, 1, 1, 0x46])
    iwram[0x3150:0x315C] = bytes([0x26, 0, 0, 0xAA, 0x46, 1, 1, 0, 0xFF, 255, 255, 255])
    for slot in (1, 2):
        base = 0x23284 + slot * 60
        ewram[base + 0x1A] = slot
        ewram[base + 0x1B] = slot
        ewram[base + 0x1D] = slot
        ewram[base + 0x2A] = slot - 1
    ewram[0x22690:0x2269C] = bytes([1, 0, 0, 0, 100, 0, 99, 0, 0, 0, 0, 0])
    ewram[0x22990:0x2299C] = bytes([1, 0, 1, 1, 0xE4, 0, 99, 0, 0, 0, 0, 0])
    pack_into("<I", iwram, 0x3F3C, 1)
    pack_into("<H", iwram, 0x32D8, 13)
    pack_into("<H", iwram, 0x33EC, 1)
    pack_into("<H", iwram, 0x4080, 1)
    pack_into("<I", iwram, 0x40D0, BATTLE_CALLBACKS[0])
    pack_into("<I", iwram, 0x40EC, BATTLE_CALLBACKS[1])
    return layout, ewram, iwram


def snapshot(memory: tuple[BattleLayout, bytearray, bytearray]) -> BattleMemorySnapshot:
    layout, ewram, iwram = memory
    return BattleMemorySnapshot(123, layout, bytes(ewram), bytes(iwram))


def test_consistent_battle_allows_the_supported_live_fields(memory) -> None:
    report = validate_battle_snapshot(snapshot(memory))
    assert report.can_decode_live
    assert report.geometry.count == 4
    assert report.properties.count == 2
    assert report.players.count == 2
    assert report.units.count == 2
    report.require_live()


def test_map_cursor_observation_requires_live_phase_and_matching_bounded_coordinates(
    memory,
) -> None:
    _, _, iwram = memory
    pack_into("<HH", iwram, 0x33E4, 1, 1)
    iwram[0x3140:0x3142] = bytes((1, 1))
    current = snapshot(memory)
    report = validate_battle_snapshot(current)
    cursor = observe_map_cursor(current, report)
    assert cursor.status is CursorStatus.AVAILABLE
    assert (cursor.x, cursor.y) == (1, 1)

    iwram[0x3140:0x3142] = bytes((0, 1))
    current = snapshot(memory)
    cursor = observe_map_cursor(current, validate_battle_snapshot(current))
    assert cursor.status is CursorStatus.UNAVAILABLE
    assert cursor.x is None and cursor.y is None
    assert "do not agree" in cursor.reasons[0]

    pack_into("<HH", iwram, 0x33E4, 2, 1)
    iwram[0x3140:0x3142] = bytes((2, 1))
    current = snapshot(memory)
    cursor = observe_map_cursor(current, validate_battle_snapshot(current))
    assert cursor.status is CursorStatus.UNAVAILABLE
    assert "outside the validated map" in cursor.reasons[0]


@pytest.mark.parametrize(
    ("script", "callbacks", "phase"),
    [
        (0x0849ECE0, SCREEN_CALLBACKS, LifecyclePhase.VERSUS_SETUP),
        (0x084892C4, BATTLE_CALLBACKS, LifecyclePhase.BATTLE_TRANSITION),
    ],
)
def test_map_cursor_is_unavailable_during_setup_and_battle_entry(
    memory, script, callbacks, phase
) -> None:
    _, ewram, iwram = memory
    pack_into("<HH", iwram, 0x33E4, 1, 1)
    iwram[0x3140:0x3142] = bytes((1, 1))
    pack_into("<I", ewram, 0xD610, script)
    for offset, callback in zip((0x40D0, 0x40EC), callbacks, strict=True):
        pack_into("<I", iwram, offset, callback)
    current = snapshot(memory)
    report = validate_battle_snapshot(current)
    cursor = observe_map_cursor(current, report)
    assert report.lifecycle.phase is phase
    assert cursor.status is CursorStatus.UNAVAILABLE
    assert cursor.x is None and cursor.y is None
    assert "not a player turn" in cursor.reasons[0]


def test_map_cursor_observation_rejects_cross_frame_validation(memory) -> None:
    current = snapshot(memory)
    report = replace(validate_battle_snapshot(current), frame=current.frame + 1)
    with pytest.raises(ValueError, match="same frame"):
        observe_map_cursor(current, report)


def test_unit_action_menu_resolves_selected_unit_against_table_and_map(memory) -> None:
    _, ewram, iwram = memory
    pack_into("<I", ewram, 0xD610, 0x0849BE38)
    pack_into("<I", iwram, 0x40D8, 0x02022690)
    pack_into("<H", iwram, 0x3334, 4)
    ewram[0x22690:0x2269C] = bytes((1, 6, 1, 1, 100, 0, 99, 0, 0, 0, 0, 0))
    iwram[0x3140:0x3142] = bytes((1, 1))
    ewram[0x1E450 + 0x51A + 3] = 1

    current = snapshot(memory)
    report = validate_battle_snapshot(current)
    menu = observe_menu(current, report)
    assert report.lifecycle.phase is LifecyclePhase.BATTLE_ENGINE_UNRESOLVED
    assert menu.family is MenuFamily.UNIT_ACTION
    assert menu.selected_unit is not None, menu.reasons
    assert menu.selected_unit.record_address == 0x02022690
    assert (menu.selected_unit.army_slot, menu.selected_unit.unit_slot) == (1, 1)
    assert menu.selected_unit.unit_type == 1
    assert (menu.selected_unit.x, menu.selected_unit.y) == (1, 1)


def test_unit_action_menu_rejects_a_pointer_from_another_army(memory) -> None:
    _, ewram, iwram = memory
    pack_into("<I", ewram, 0xD610, 0x0849BE38)
    pack_into("<I", iwram, 0x40D8, 0x02022990)
    ewram[0x22990:0x2299C] = bytes((1, 6, 1, 1, 100, 0, 99, 0, 0, 0, 0, 0))
    iwram[0x3140:0x3142] = bytes((1, 1))
    ewram[0x1E450 + 0x51A + 3] = 65

    current = snapshot(memory)
    menu = observe_menu(current, validate_battle_snapshot(current))
    assert menu.family is MenuFamily.UNIT_ACTION
    assert menu.selected_unit is None
    assert "does not match the active player" in menu.reasons[0]


def test_unit_movement_overlay_exposes_verified_source_cursor(memory) -> None:
    _, ewram, iwram = memory
    pack_into("<I", ewram, 0xD610, 0x0849BE38)
    pack_into("<I", iwram, 0x40D8, 0x02022690)
    pack_into("<I", iwram, 0x1470, 0x08499B4C)
    pack_into("<I", iwram, 0x1490, 8)
    iwram[0x14B1] = 6
    iwram[0x14B2] = 2
    iwram[0x30F0] = 0
    pack_into("<H", iwram, 0x3334, 1)
    ewram[0x22690:0x2269C] = bytes((1, 6, 1, 1, 100, 0, 99, 0, 0, 0, 0, 0))
    pack_into("<HH", iwram, 0x33E4, 0, 1)
    iwram[0x3140:0x3142] = bytes((1, 1))  # Cache lags while the range cursor moves.
    ewram[0x1E450 + 0x51A + 3] = 1

    current = snapshot(memory)
    report = validate_battle_snapshot(current)
    menu = observe_menu(current, report)
    cursor = observe_map_cursor(current, report)
    assert menu.family is MenuFamily.UNIT_MOVEMENT
    assert menu.selected_unit is not None, menu.reasons
    assert cursor.status is CursorStatus.AVAILABLE
    assert (cursor.x, cursor.y) == (0, 1)


@pytest.mark.parametrize(
    ("action_ids", "selected_item"),
    [
        ((0, 0x0A), MenuItem.OTHER_UNIT_ACTION),
        ((2, 0x0A), MenuItem.OTHER_UNIT_ACTION),
        ((4, 0x0A), MenuItem.OTHER_UNIT_ACTION),
        ((0x0A, 0x0B), MenuItem.WAIT),
    ],
)
def test_unit_action_choices_resolve_wait_from_verified_row_ids(
    memory, action_ids: tuple[int, int], selected_item: MenuItem
) -> None:
    _, ewram, iwram = memory
    pack_into("<I", ewram, 0xD610, 0x0849BE38)
    pack_into("<I", iwram, 0x40D8, 0x02022690)
    pack_into("<H", iwram, 0x3334, 4)
    pack_into("<I", iwram, 0x1470, 0x0848A42C)
    pack_into("<I", iwram, 0x1490, 0x0849AE28)
    iwram[0x14B1] = 2
    iwram[0x14B2] = 0
    iwram[0x14A1:0x14A3] = bytes(action_ids)
    iwram[0x30F0] = 1
    ewram[0x22690:0x2269C] = bytes((1, 6, 1, 1, 100, 0, 99, 0, 0, 0, 0, 0))
    iwram[0x3140:0x3142] = bytes((1, 1))
    ewram[0x1E450 + 0x51A + 3] = 1

    current = snapshot(memory)
    menu = observe_menu(current, validate_battle_snapshot(current))
    assert menu.family is MenuFamily.UNIT_ACTION_CHOICES
    assert menu.items == tuple(
        MenuItem.WAIT if item_id == 0x0A else MenuItem.OTHER_UNIT_ACTION for item_id in action_ids
    )
    assert menu.selected_item is selected_item


def test_general_command_menu_stays_unresolved_and_does_not_publish_stale_pointer(memory) -> None:
    _, _, iwram = memory
    pack_into("<I", iwram, 0x40D8, 0x02022690)
    iwram[0x30F0] = 1
    current = snapshot(memory)
    menu = observe_menu(current, validate_battle_snapshot(current))
    assert menu.family is MenuFamily.UNRESOLVED
    assert menu.selected_unit is None


def test_map_input_menu_does_not_treat_current_pointer_as_selection(memory) -> None:
    pack_into("<I", memory[2], 0x40D8, 0x02022690)
    current = snapshot(memory)
    menu = observe_menu(current, validate_battle_snapshot(current))
    assert menu.family is MenuFamily.MAP_INPUT
    assert menu.selected_unit is None


def test_menu_observation_rejects_cross_frame_validation(memory) -> None:
    current = snapshot(memory)
    report = replace(validate_battle_snapshot(current), frame=current.frame + 1)
    with pytest.raises(ValueError, match="same frame"):
        observe_menu(current, report)


@pytest.mark.parametrize(
    "script", [0x08616C54, 0x0849ECE0, 0x08615CB0, 0x084C327C, 0x08615FB4, 0x0849F330]
)
def test_consistent_retained_data_is_unavailable_in_menus_and_results(memory, script) -> None:
    _, ewram, iwram = memory
    pack_into("<I", ewram, 0xD610, script)
    for offset, value in zip((0x40D0, 0x40EC), SCREEN_CALLBACKS, strict=True):
        pack_into("<I", iwram, offset, value)
    report = validate_battle_snapshot(snapshot(memory))
    assert all(
        getattr(report, name).status is ValidationStatus.VALID
        for name in ("geometry", "properties", "players", "units")
    )
    assert not any(report.available(name) for name in BattleStructure)
    with pytest.raises(ValueError, match="Lifecycle phase"):
        report.require_live()


@pytest.mark.parametrize("state", [5, 9, 12, 14])
def test_consistent_arrays_do_not_make_entry_gaps_or_computer_turns_live(memory, state) -> None:
    pack_into("<H", memory[2], 0x32D8, state)
    assert not validate_battle_snapshot(snapshot(memory)).can_decode_live


def test_valid_structures_stay_unavailable_through_combat_and_cleanup(memory) -> None:
    _, ewram, iwram = memory
    assert validate_battle_snapshot(snapshot(memory)).can_decode_live
    for callbacks in (BATTLE_CALLBACKS, ANIMATION_CALLBACKS, BATTLE_CALLBACKS):
        for offset, value in zip((0x40D0, 0x40EC), callbacks, strict=True):
            pack_into("<I", iwram, offset, value)
        pack_into("<I", ewram, 0xD610, 0x0849A9F8)
        pack_into("<I", ewram, 0xD67C, 0x0849FEF8)
        report = validate_battle_snapshot(snapshot(memory))
        assert report.lifecycle.phase is LifecyclePhase.BATTLE_COMBAT
        assert all(
            getattr(report, field.value).status is ValidationStatus.VALID
            for field in BattleStructure
        )
        assert not any(report.available(field) for field in BattleStructure)
        with pytest.raises(ValueError, match="battle_combat"):
            report.require_live()

    pack_into("<I", ewram, 0xD610, 0)
    pack_into("<I", ewram, 0xD67C, 0)
    pack_into("<H", iwram, 0x3334, 4)
    for state in (16, 13):
        pack_into("<H", iwram, 0x32D8, state)
        assert not validate_battle_snapshot(snapshot(memory)).can_decode_live
    pack_into("<H", iwram, 0x3334, 0)
    report = validate_battle_snapshot(snapshot(memory))
    assert report.can_decode_live
    report.require_live()


@pytest.mark.parametrize("script", [0x0849FEF8, 0x0849FFB0])
def test_computer_combat_is_unavailable_even_without_a_fire_parent(memory, script) -> None:
    pack_into("<I", memory[1], 0xD610, script)
    pack_into("<H", memory[2], 0x32D8, 14)
    report = validate_battle_snapshot(snapshot(memory))
    assert report.lifecycle.phase is LifecyclePhase.BATTLE_COMBAT
    assert not report.can_decode_live


@pytest.mark.parametrize("active_power", [1, 2])
def test_power_sequence_blocks_valid_arrays_but_active_power_does_not(memory, active_power) -> None:
    _, ewram, _ = memory
    ewram[0x23284 + 60 + 0x1E] = active_power
    pack_into("<I", ewram, 0xD610, 0x0849D77C)
    report = validate_battle_snapshot(snapshot(memory))
    assert report.lifecycle.phase is LifecyclePhase.BATTLE_POWER
    assert all(
        getattr(report, field.value).status is ValidationStatus.VALID for field in BattleStructure
    )
    assert not report.can_decode_live
    pack_into("<I", ewram, 0xD610, 0)
    assert validate_battle_snapshot(snapshot(memory)).can_decode_live


def test_resume_and_process_free_dialogues_require_the_normal_controller(memory) -> None:
    # Resumed battle arrays can be valid before state 12 advances to state 13.
    for state, lock_count in ((12, 1), (12, 0), (13, 1)):
        pack_into("<H", memory[2], 0x32D8, state)
        memory[2][0x30F0] = lock_count
        report = validate_battle_snapshot(snapshot(memory))
        assert all(
            getattr(report, field.value).status is ValidationStatus.VALID
            for field in BattleStructure
        )
        assert not report.can_decode_live
    memory[2][0x30F0] = 0
    assert validate_battle_snapshot(snapshot(memory)).can_decode_live


@pytest.mark.parametrize("width,height", [(0, 0), (49, 15), (48, 39), (65535, 65535)])
def test_unsupported_dimensions_stop_dependent_reads(memory, width, height) -> None:
    pack_into("<HH", memory[1], 0x1E450, width, height)
    report = validate_battle_snapshot(snapshot(memory))
    assert not report.available(BattleStructure.GEOMETRY)
    assert report.properties.status is ValidationStatus.UNKNOWN
    assert report.units.status is ValidationStatus.UNKNOWN


def test_bad_row_offset_never_gets_followed(memory) -> None:
    pack_into("<H", memory[1], 0x225CC, 65535)
    report = validate_battle_snapshot(snapshot(memory))
    assert report.geometry.status is ValidationStatus.INVALID
    assert not report.can_decode_live


@pytest.mark.parametrize("tile", [4, 1024, 65535])
def test_tile_lookup_bounds_and_terrain_mismatch(memory, tile) -> None:
    pack_into("<H", memory[1], 0x1EE72, tile)
    assert validate_battle_snapshot(snapshot(memory)).geometry.status is ValidationStatus.INVALID


def test_deferred_campaign_terrain_remains_unknown(memory) -> None:
    pack_into("<H", memory[1], 0x1EE72, 5)
    memory[1][0x1F882] = 9
    assert validate_battle_snapshot(snapshot(memory)).geometry.status is ValidationStatus.UNKNOWN


def test_missing_sentinel_is_bounded(memory) -> None:
    memory[2][0x3158:0x32C0] = bytes(0x168)
    report = validate_battle_snapshot(snapshot(memory))
    assert report.properties.status is ValidationStatus.INVALID
    assert any("92-slot" in reason for reason in report.properties.reasons)


def test_inactive_property_holes_and_trailing_stale_records_are_ignored(memory) -> None:
    table = memory[2]
    table[0x3154:0x3164] = bytes(
        [0, 255, 255, 255, 0x46, 1, 1, 255, 0xFF, 255, 255, 255, 0x26, 255, 255, 0]
    )
    assert validate_battle_snapshot(snapshot(memory)).properties.status is ValidationStatus.VALID


@pytest.mark.parametrize(
    "record", [bytes([0x46, 0, 0, 0]), bytes([0x26, 0, 0, 0]), bytes([0x46, 2, 1, 0]), bytes(4)]
)
def test_property_ownership_duplicates_coordinates_and_coverage(memory, record) -> None:
    memory[2][0x3154:0x3158] = record
    assert validate_battle_snapshot(snapshot(memory)).properties.status is ValidationStatus.INVALID


@pytest.mark.parametrize("offset,value", [(0x1A, 4), (0x1E, 3), (0x2A, 4)])
def test_player_slot_power_and_team_checks(memory, offset, value) -> None:
    memory[1][0x232C0 + offset] = value
    assert validate_battle_snapshot(snapshot(memory)).players.status is ValidationStatus.INVALID


def test_inactive_player_bytes_are_ignored_but_owners_cannot_reference_them(memory) -> None:
    record = 0x23284 + 4 * 60
    memory[1][record : record + 60] = bytes([255]) * 60
    memory[1][record + 0x1B] = 0
    assert validate_battle_snapshot(snapshot(memory)).players.status is ValidationStatus.VALID
    memory[1][0x23284 + 2 * 60 + 0x1B] = 0
    report = validate_battle_snapshot(snapshot(memory))
    assert report.properties.status is ValidationStatus.INVALID
    assert report.units.status is ValidationStatus.INVALID


def test_corrupt_turn_pointer_is_not_followed(memory) -> None:
    pack_into("<H", memory[2], 0x33EC, 65535)
    report = validate_battle_snapshot(snapshot(memory))
    assert not report.can_decode_live
    with pytest.raises(ValueError, match="bounded player table"):
        report.require_live()


def test_defeated_current_player_cannot_be_used_as_a_live_turn(memory) -> None:
    pack_into("<H", memory[1], 0x232C0 + 0x14, 1)
    assert not validate_battle_snapshot(snapshot(memory)).can_decode_live


@pytest.mark.parametrize("offset,value", [(2, 2), (4, 0), (4, 127), (5, 160)])
def test_bad_unit_coordinates_health_and_capture_progress(memory, offset, value) -> None:
    memory[1][0x22690 + offset] = value
    assert validate_battle_snapshot(snapshot(memory)).units.status is ValidationStatus.INVALID


def test_empty_units_ignore_stale_bytes_and_unknown_types_fail_closed(memory) -> None:
    memory[1][0x2269C:0x226A8] = bytes([0] + [255] * 11)
    assert validate_battle_snapshot(snapshot(memory)).units.status is ValidationStatus.VALID
    memory[1][0x22690] = 255
    assert validate_battle_snapshot(snapshot(memory)).units.status is ValidationStatus.UNKNOWN


def test_blue_cargo_is_a_global_index_and_need_not_share_current_coordinates(memory) -> None:
    raw = memory[1]
    raw[0x22990] = 7
    raw[0x22997] = 66
    raw[0x2299C:0x229A8] = bytes([1, 0, 0, 0, 100, 0, 99, 0, 0, 0, 0, 0])
    assert validate_battle_snapshot(snapshot(memory)).units.status is ValidationStatus.VALID


@pytest.mark.parametrize("ref", [1, 64, 65, 66, 115, 255])
def test_bad_cargo_foreign_reserved_empty_self_and_out_of_range_references(memory, ref) -> None:
    memory[1][0x22990] = 7
    memory[1][0x22997] = ref
    assert validate_battle_snapshot(snapshot(memory)).units.status is ValidationStatus.INVALID


def test_cargo_cycles_are_rejected(memory) -> None:
    raw = memory[1]
    raw[0x22690] = 7
    raw[0x22697] = 2
    raw[0x2269C:0x226A8] = bytes([7, 0, 0, 0, 100, 0, 99, 1, 0, 0, 0, 0])
    assert any("cycle" in r for r in validate_battle_snapshot(snapshot(memory)).units.reasons)


def test_duplicate_passenger_references_are_rejected(memory) -> None:
    raw = memory[1]
    raw[0x22690] = 23
    raw[0x22697:0x22699] = bytes([2, 2])
    raw[0x2269C:0x226A8] = bytes([1, 0, 0, 0, 100, 0, 99, 0, 0, 0, 0, 0])
    report = validate_battle_snapshot(snapshot(memory))
    assert any("more than once" in reason for reason in report.units.reasons)


@pytest.mark.parametrize("slot", [0, 51, 63])
def test_units_in_reserved_slots_are_unavailable(memory, slot) -> None:
    offset = 0x22684 + slot * 12
    memory[1][offset : offset + 12] = memory[1][0x22690:0x2269C]
    assert validate_battle_snapshot(snapshot(memory)).units.status is ValidationStatus.UNKNOWN


def test_largest_observed_retail_area_fits_the_bounded_arrays(memory) -> None:
    raw = memory[1]
    pack_into("<HH", raw, 0x1E450, 46, 28)
    pack_into("<28H", raw, 0x225CA, *(y * 46 for y in range(28)))
    pack_into("<1288H", raw, 0x1EE72, *([1] * 1288))
    raw[0x1F882:0x1FD8A] = bytes([1]) * 1288
    memory[2][0x3150] = 255
    report = validate_battle_snapshot(snapshot(memory))
    assert report.can_decode_live
    assert report.geometry.count == 1288


def test_eighty_eight_observed_properties_fit_below_the_reader_bound(memory) -> None:
    raw, control = memory[1], memory[2]
    pack_into("<HH", raw, 0x1E450, 11, 8)
    pack_into("<8H", raw, 0x225CA, *(y * 11 for y in range(8)))
    pack_into("<88H", raw, 0x1EE72, *([2] * 88))
    raw[0x1F882:0x1F8DA] = bytes([6]) * 88
    for index in range(88):
        offset = 0x3150 + index * 4
        control[offset : offset + 4] = bytes([6, index % 11, index // 11, 0])
    control[0x3150 + 88 * 4] = 255
    report = validate_battle_snapshot(snapshot(memory))
    assert report.can_decode_live
    assert report.properties.count == 88


def test_unknown_rom_pointers_and_truncated_snapshots_are_rejected(memory, tmp_path) -> None:
    layout = memory[0]
    with pytest.raises(ValueError, match="pointers"):
        replace(layout, unit_base=layout.unit_base + 4)
    with pytest.raises(UnsupportedRomError):
        replace(layout, profile=replace(layout.profile, sha256="0" * 64))
    with pytest.raises(ValueError, match="complete"):
        replace(snapshot(memory), iwram=b"")
    rom = tmp_path / "unknown.gba"
    rom.write_bytes(b"not a supported ROM")
    with pytest.raises(UnsupportedRomError):
        load_battle_layout(rom)


class SnapshotBridge(LuaBridgeClient):
    def __init__(self, source: BattleMemorySnapshot, *, drift: bool, truncate: bool) -> None:
        super().__init__()
        self.source = source
        self.drift = drift
        self.truncate = truncate
        self.reads = 0
        self.final_drift = False

    async def advance_frames(self, frames: int) -> int:
        return self.source.frame + int(self.final_drift and self.reads > 0)

    async def read_memory_snapshot(self, ranges: list[tuple[int, int]]) -> MemorySnapshot:
        self.reads += 1
        values = tuple(self.source.read(address, size) for address, size in ranges)
        if self.truncate:
            values = (values[0][:-1],)
        return MemorySnapshot(self.source.frame + int(self.drift), values)


@pytest.mark.parametrize("drift,truncate", [(True, False), (False, True)])
def test_capture_rejects_frame_drift_and_incomplete_reads(memory, drift, truncate) -> None:
    bridge = SnapshotBridge(snapshot(memory), drift=drift, truncate=truncate)
    with pytest.raises(BridgeError):
        asyncio.run(capture_battle_snapshot(bridge, memory[0]))


def test_capture_round_trip(memory) -> None:
    original = snapshot(memory)
    bridge = SnapshotBridge(original, drift=False, truncate=False)
    captured = asyncio.run(capture_battle_snapshot(bridge, memory[0]))
    assert captured == original


def test_capture_checks_frame_again_after_the_last_read(memory) -> None:
    bridge = SnapshotBridge(snapshot(memory), drift=False, truncate=False)
    bridge.final_drift = True
    with pytest.raises(BridgeError, match="changed frames"):
        asyncio.run(capture_battle_snapshot(bridge, memory[0]))
