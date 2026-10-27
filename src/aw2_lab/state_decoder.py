"""Coherent, conservative decoding of the documented AW2 memory subset."""

from pathlib import Path

from aw2_lab.bridge import LuaBridgeClient
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
    Weather,
)
from aw2_lab.state_validation import (
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


def decode_snapshot(snapshot: BattleMemorySnapshot) -> GameState:
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
            observe_menu(snapshot, report),
        ),
        battle=battle,
    )


async def capture_game_state(bridge: LuaBridgeClient, *, rom_path: Path) -> GameState:
    """Verify the ROM, capture RAM without advancing frames, and decode it.

    The capture checks each response and the final frame boundary. An unsupported
    ROM fails before any bridge operation; drift or truncated reads fail before
    any state is published.
    """
    layout = load_battle_layout(rom_path)
    return decode_snapshot(await capture_battle_snapshot(bridge, layout))


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

    properties = []
    for index in range(PROPERTY_SLOTS):
        encoded, x, y, _ = snapshot.read(PROPERTY_BASE + index * 4, 4)
        if encoded == 0xFF:
            break
        if encoded:
            properties.append(PropertyState(x, y, encoded & 31, encoded >> 5))

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
        day=snapshot.u16(0x03004080),
        active_player_slot=snapshot.u16(0x030033EC),
        weather=weather_observation,
        map=MapState(width, height, tuple(tiles)),
        properties=tuple(properties),
        players=tuple(players),
        units=tuple(units),
    )
