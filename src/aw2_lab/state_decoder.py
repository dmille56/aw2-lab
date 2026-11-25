"""Coherent, conservative decoding of the documented AW2 memory subset."""

from pathlib import Path

from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.map_catalog import MAPS_BY_ID
from aw2_lab.match_contract import FixedMatchConfiguration
from aw2_lab.state_model import (
    GAME_STATE_SCHEMA_VERSION,
    BattleState,
    GameState,
    MapState,
    ObservedValue,
    PlayerState,
    PropertyState,
    StateContext,
    TileState,
    UIStateObservation,
    UnitState,
    ValueStatus,
    VersusOutcome,
    VersusPlayerResult,
    Weather,
)
from aw2_lab.state_validation import (
    BATTLE_MAP_ID_ADDRESS,
    MAP_BASE,
    PLAYER_BASE,
    PLAYER_STRIDE,
    PROPERTY_BASE,
    PROPERTY_SLOTS,
    UNIT_BASE,
    UNIT_STRIDE,
    UNITS_PER_ARMY,
    BattleMemorySnapshot,
    BattleStructure,
    BattleValidationReport,
    ValidationStatus,
    capture_battle_snapshot,
    load_battle_layout,
    validate_battle_snapshot,
)
from aw2_lab.ui_state import observe_map_cursor, observe_menu


def decode_snapshot(
    snapshot: BattleMemorySnapshot, *, versus: FixedMatchConfiguration | None = None
) -> GameState:
    """Decode immutable RAM only after validating this exact snapshot.

    Offline callers are responsible for capturing both RAM regions at one frame.
    No emulator operations or identity-ledger mutations occur here.
    """
    report = validate_battle_snapshot(snapshot)
    battle = (
        ObservedValue(ValueStatus.AVAILABLE, _decode_battle(snapshot))
        if report.can_decode_live
        else _blocked_battle(report)
    )
    return GameState(
        schema_version=GAME_STATE_SCHEMA_VERSION,
        frame=snapshot.frame,
        context=StateContext(snapshot.layout.profile),
        validation=report,
        ui=UIStateObservation(
            snapshot.frame,
            observe_map_cursor(snapshot, report),
            observe_menu(
                snapshot,
                report,
                _decode_properties(snapshot)
                if report.properties.status is ValidationStatus.VALID
                else (),
            ),
        ),
        battle=battle,
        versus_result=_decode_versus_result(snapshot, report.lifecycle.phase, versus),
    )


async def capture_game_state(
    bridge: LuaBridgeClient,
    *,
    rom_path: Path,
    versus: FixedMatchConfiguration | None = None,
) -> GameState:
    """Verify the ROM, capture RAM without advancing frames, and decode it.

    The capture checks each response and the final frame boundary. An unsupported
    ROM fails before any bridge operation; drift or truncated reads fail before
    any state is published.
    """
    layout = load_battle_layout(rom_path)
    return decode_snapshot(await capture_battle_snapshot(bridge, layout), versus=versus)


_RESULT_PHASES = frozenset(
    {
        LifecyclePhase.RESULT_SEQUENCE,
        LifecyclePhase.VICTORY_PRESENTATION,
        LifecyclePhase.DEFEAT_PRESENTATION,
        LifecyclePhase.RESULT_SUMMARY,
        LifecyclePhase.SAVE_PROGRESS_PROMPT,
    }
)
_GAME_MODE_ADDRESS = 0x03003FC1
_VERSUS_MODE = 3
_BATTLE_DAY_ADDRESS = 0x03004080
_TURN_LIMIT_ADDRESS = 0x03003FF0


def _decode_versus_result(
    snapshot: BattleMemorySnapshot,
    phase: LifecyclePhase,
    versus: FixedMatchConfiguration | None,
) -> tuple[VersusPlayerResult, ...] | None:
    if versus is None or phase not in _RESULT_PHASES:
        return None
    slots = versus.player_slots
    unknown = tuple(VersusPlayerResult(slot, VersusOutcome.UNKNOWN) for slot in slots)
    if phase is LifecyclePhase.RESULT_SEQUENCE:
        return unknown  # The result process may still be updating the records.

    mode = snapshot.read(_GAME_MODE_ADDRESS, 1)[0]
    map_id = snapshot.read(BATTLE_MAP_ID_ADDRESS, 1)[0]
    day = snapshot.u16(_BATTLE_DAY_ADDRESS)
    if mode != _VERSUS_MODE or map_id != MAPS_BY_ID[versus.map_id].rom_id or day == 0:
        return unknown
    records = tuple(
        snapshot.read(PLAYER_BASE + index * PLAYER_STRIDE, PLAYER_STRIDE) for index in range(1, 5)
    )
    teams = versus.team_ids
    for index, record in enumerate(records, 1):
        if index > len(slots):
            if record[0x1B] != 0:
                return unknown
        elif (
            record[0x1A] != index
            or record[0x1B] != 1
            or record[0x1D] > 18
            or record[0x2A] != teams[index - 1]
        ):
            return unknown
    markers = tuple(int.from_bytes(record[0x14:0x16], "little") for record in records[: len(slots)])
    if any(marker > day for marker in markers) or all(markers):
        return unknown
    if any(markers):
        winning_teams = {team for team, marker in zip(teams, markers, strict=True) if not marker}
        losing_teams = {team for team, marker in zip(teams, markers, strict=True) if marker}
        if winning_teams & losing_teams:
            return unknown  # This boundary has not established a common team result.
        return tuple(
            VersusPlayerResult(slot, VersusOutcome.LOSS if marker else VersusOutcome.WIN)
            for slot, marker in zip(slots, markers, strict=True)
        )
    # A confirmed turn-limit presentation with no defeated participants is
    # a draw. A top-score tie can use the same script with nonzero markers.
    if (
        phase is LifecyclePhase.DEFEAT_PRESENTATION
        and day == versus.rules.day_limit
        and snapshot.read(_TURN_LIMIT_ADDRESS, 1)[0] == day
    ):
        return tuple(VersusPlayerResult(slot, VersusOutcome.DRAW) for slot in slots)
    return unknown


def _blocked_battle(report: BattleValidationReport) -> ObservedValue[BattleState]:
    reasons = list(report.live_reasons)
    invalid = False
    for structure in BattleStructure:
        result = getattr(report, structure.value)
        if result.status is not ValidationStatus.VALID:
            invalid |= result.status is ValidationStatus.INVALID
            reasons.extend(
                f"{structure.value}: {reason}"
                for reason in result.reasons or (result.status.value,)
            )
    status = ValueStatus.UNAVAILABLE if report.live_reasons or invalid else ValueStatus.UNKNOWN
    return ObservedValue(status, None, tuple(reasons))


def _decode_battle(snapshot: BattleMemorySnapshot) -> BattleState:
    """Read only structures whose complete validation and live gates have passed."""
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    tiles = []
    for y in range(height):
        for x in range(width):
            index = y * width + x
            encoded = snapshot.read(MAP_BASE + 0x1432 + index, 1)[0]
            tiles.append(
                TileState(
                    x,
                    y,
                    snapshot.u16(MAP_BASE + 0x0A22 + 2 * index),
                    encoded & 31,
                    encoded >> 5,
                )
            )

    properties = _decode_properties(snapshot)

    players = []
    for slot in range(1, 5):
        address = PLAYER_BASE + slot * PLAYER_STRIDE
        record = snapshot.read(address, PLAYER_STRIDE)
        if record[0x1B]:
            raw_meter = int.from_bytes(snapshot.read(address + 0x20, 4), "little", signed=True)
            meter = (
                ObservedValue(ValueStatus.AVAILABLE, raw_meter)
                if raw_meter >= 0
                else ObservedValue[int](
                    ValueStatus.UNKNOWN,
                    None,
                    (f"Negative power-meter value is not validated: {raw_meter}",),
                )
            )
            raw_counter = record[0x25]
            use_counter = (
                ObservedValue(ValueStatus.AVAILABLE, raw_counter)
                if raw_counter <= 10
                else ObservedValue[int](
                    ValueStatus.UNKNOWN,
                    None,
                    (
                        f"Power-use counter above 10 is outside runtime-verified range: {raw_counter}",
                    ),
                )
            )
            players.append(
                PlayerState(
                    slot=slot,
                    control_type=record[0x1B],
                    team_id=record[0x2A],
                    co_id=record[0x1D],
                    funds=snapshot.u32(address),
                    active_power=record[0x1E],
                    power_meter=meter,
                    power_use_counter=use_counter,
                    # Native 0x08024C58 adds these signed player-record bonuses.
                    attack_bonus=ObservedValue(
                        ValueStatus.AVAILABLE,
                        int.from_bytes(record[0x26:0x28], "little", signed=True),
                    ),
                    defense_bonus=ObservedValue(
                        ValueStatus.AVAILABLE,
                        int.from_bytes(record[0x28:0x2A], "little", signed=True),
                    ),
                )
            )

    units = []
    for army in range(4):
        for slot in range(1, UNITS_PER_ARMY + 1):
            reference = army * 64 + slot
            record = snapshot.read(UNIT_BASE + reference * UNIT_STRIDE, UNIT_STRIDE)
            if not record[0]:
                continue
            packed = int.from_bytes(record[4:6], "little")
            units.append(
                UnitState(
                    reference=reference,
                    army_slot=army + 1,
                    unit_slot=slot,
                    unit_type=record[0],
                    x=record[2],
                    y=record[3],
                    internal_health=packed & 0x7F,
                    ammo=(packed >> 7) & 15,
                    fuel=record[6] & 0x7F,
                    used_this_turn=bool(record[1] & 1),
                    embarked=bool(record[1] & 8),
                    capture_points=record[5] >> 3,
                    cargo_references=tuple(ref for ref in record[7:9] if ref),
                    submerged=record[0] == 24 and bool(record[1] & 0x20),
                )
            )

    raw_weather = snapshot.read(0x03003FEC, 1)[0]
    weather = {0: Weather.CLEAR, 1: Weather.SNOW, 2: Weather.RAIN}.get(raw_weather)
    weather_observation = (
        ObservedValue(ValueStatus.AVAILABLE, weather)
        if weather is not None
        else ObservedValue[Weather](
            ValueStatus.UNKNOWN, None, (f"Unsupported current weather value {raw_weather}",)
        )
    )
    return BattleState(
        day=snapshot.u16(_BATTLE_DAY_ADDRESS),
        active_player_slot=snapshot.u16(0x030033EC),
        weather=weather_observation,
        map=MapState(width, height, tuple(tiles)),
        properties=tuple(properties),
        players=tuple(players),
        units=tuple(units),
        co_effects_enabled=_decode_rule_toggle(snapshot, 0x03003FC8),
        fog_enabled=_decode_rule_toggle(snapshot, 0x03003FCD),
    )


def _decode_properties(snapshot: BattleMemorySnapshot) -> tuple[PropertyState, ...]:
    """Decode the property table after its independent structural validation."""
    properties = []
    for index in range(PROPERTY_SLOTS):
        encoded, x, y, _ = snapshot.read(PROPERTY_BASE + index * 4, 4)
        if encoded == 0xFF:
            break
        if encoded:
            properties.append(PropertyState(x, y, encoded & 31, encoded >> 5))
    return tuple(properties)


def _decode_rule_toggle(snapshot: BattleMemorySnapshot, address: int) -> ObservedValue[bool]:
    """Decode traced boolean branches; unsupported encodings stay unknown."""
    raw = snapshot.read(address, 1)[0]
    if raw not in (0, 1):
        return ObservedValue(
            ValueStatus.UNKNOWN, None, (f"Unsupported rule byte at {address:#010x}: {raw}",)
        )
    return ObservedValue(ValueStatus.AVAILABLE, raw == 1)
