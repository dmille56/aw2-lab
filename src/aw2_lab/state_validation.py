"""Bounded structural checks and lifecycle guards for the researched ROM layout.

This validates the supported fields, rather than decoding a complete game state.
Structural consistency alone cannot establish that retained memory is live.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from struct import unpack_from

from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.lifecycle import (
    BattleControlObservation,
    LifecycleAssessment,
    LifecyclePhase,
    classify_lifecycle,
)
from aw2_lab.rom_profile import AW2_US_REVISION_0, RomProfile, UnsupportedRomError

EWRAM_BASE = 0x02000000
IWRAM_BASE = 0x03000000
MAP_BASE = 0x0201E450
UNIT_BASE = 0x02022684
PLAYER_BASE = 0x02023284
PROPERTY_BASE = 0x03003150
PROPERTY_SLOTS = 92
UNIT_STRIDE = 12
ARMY_STRIDE = 0x300
PLAYER_STRIDE = 0x3C
UNITS_PER_ARMY = 50

# Supported retail observations, not claims about arbitrary engine maxima.
MAX_WIDTH = 48
MAX_HEIGHT = 39
MAX_CELLS = 1288
MAX_TILE_ID = 470
FEATURE_CLASSES = frozenset({6, 8, 10, 11, 14, 17, 18})
TERRAIN_CLASSES = frozenset(range(1, 9)) | frozenset(range(10, 20))
UNIT_TYPES = frozenset({1, 2, 3, 5, 6, 7, 8, 10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24})


class ValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class BattleStructure(StrEnum):
    GEOMETRY = "geometry"
    PROPERTIES = "properties"
    PLAYERS = "players"
    UNITS = "units"


@dataclass(frozen=True, slots=True)
class BattleLayout:
    """ROM-derived layout metadata; obtain real metadata through load_battle_layout."""

    profile: RomProfile
    map_base: int
    unit_base: int
    player_base: int
    terrain_by_tile: bytes
    menu_rules_by_map: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.profile != AW2_US_REVISION_0:
            raise UnsupportedRomError("Battle validation requires the supported US ROM profile")
        if (self.map_base, self.unit_base, self.player_base) != (
            MAP_BASE,
            UNIT_BASE,
            PLAYER_BASE,
        ):
            raise ValueError("ROM pointers do not match the supported battle layout")
        if len(self.terrain_by_tile) != 1024:
            raise ValueError("The ROM tile lookup must contain 1024 bytes")
        if len(self.menu_rules_by_map) != 256:
            raise ValueError("Menu eligibility metadata must cover every byte-sized map ID")


def load_battle_layout(rom_path: Path) -> BattleLayout:
    """Verify ROM identity before following its fixed layout literals."""
    # Read/hash the same bytes to avoid mixing a verified file with a later edit.
    raw = rom_path.read_bytes()
    if sha256(raw).hexdigest() != AW2_US_REVISION_0.sha256:
        raise UnsupportedRomError("Battle validation requires the supported US ROM checksum")
    return BattleLayout(
        profile=AW2_US_REVISION_0,
        map_base=unpack_from("<I", raw, 0x499590)[0],
        unit_base=unpack_from("<I", raw, 0x499594)[0],
        player_base=unpack_from("<I", raw, 0x499598)[0],
        terrain_by_tile=raw[0x0C1BC4:0x0C1FC4],
        menu_rules_by_map=tuple(
            unpack_from("<I", raw, 0x5C77A0 + map_id * 0x5C + 4)[0] for map_id in range(256)
        ),
    )


@dataclass(frozen=True, slots=True)
class BattleMemorySnapshot:
    """Complete RAM captured at one paused frame using the supplied ROM layout."""

    frame: int
    layout: BattleLayout
    ewram: bytes
    iwram: bytes

    def __post_init__(self) -> None:
        if self.frame < 0:
            raise ValueError("Snapshot frame must be nonnegative")
        if len(self.ewram) != 0x40000 or len(self.iwram) != 0x8000:
            raise ValueError("A battle snapshot requires complete EWRAM and IWRAM")

    def read(self, address: int, length: int) -> bytes:
        """Read a bounded GBA range; never interpret a GBA value as a host pointer."""
        for base, memory in ((EWRAM_BASE, self.ewram), (IWRAM_BASE, self.iwram)):
            offset = address - base
            if length >= 0 and 0 <= offset <= len(memory) - length:
                return memory[offset : offset + length]
        raise ValueError(f"Memory range outside captured RAM: {address:#010x}:{length}")

    def u16(self, address: int) -> int:
        if address % 2:
            raise ValueError("Unaligned halfword address")
        return int.from_bytes(self.read(address, 2), "little")

    def u32(self, address: int) -> int:
        if address % 4:
            raise ValueError("Unaligned word address")
        return int.from_bytes(self.read(address, 4), "little")


async def capture_battle_snapshot(
    bridge: LuaBridgeClient, layout: BattleLayout
) -> BattleMemorySnapshot:
    """Capture bounded chunks, rejecting any frame change during the operation."""
    frame = await bridge.advance_frames(0)
    memories: list[bytes] = []
    range_size = 64
    ranges_per_batch = 64
    batch_size = range_size * ranges_per_batch
    for base, length in ((EWRAM_BASE, 0x40000), (IWRAM_BASE, 0x8000)):
        raw = bytearray()
        for batch_offset in range(0, length, batch_size):
            ranges = [
                (base + offset, min(range_size, length - offset))
                for offset in range(
                    batch_offset,
                    min(batch_offset + batch_size, length),
                    range_size,
                )
            ]
            sample = await bridge.read_memory_snapshot(ranges)
            if sample.frame != frame:
                raise BridgeError("Battle memory changed frames during capture")
            if len(sample.ranges) != len(ranges) or any(
                len(value) != requested[1]
                for requested, value in zip(ranges, sample.ranges, strict=False)
            ):
                raise BridgeError("Battle capture returned an incomplete memory range")
            for value in sample.ranges:
                raw.extend(value)
        memories.append(bytes(raw))
    if await bridge.advance_frames(0) != frame:
        raise BridgeError("Battle memory changed frames during capture")
    return BattleMemorySnapshot(frame, layout, memories[0], memories[1])


@dataclass(frozen=True, slots=True)
class StructureValidation:
    status: ValidationStatus
    reasons: tuple[str, ...] = ()
    count: int | None = None


@dataclass(frozen=True, slots=True)
class BattleValidationReport:
    frame: int
    lifecycle: LifecycleAssessment
    geometry: StructureValidation
    properties: StructureValidation
    players: StructureValidation
    units: StructureValidation
    live_reasons: tuple[str, ...]

    def available(self, structure: BattleStructure) -> bool:
        """Whether the supported fields of a structure may be decoded as live."""
        dependencies = {
            BattleStructure.GEOMETRY: (self.geometry,),
            BattleStructure.PROPERTIES: (self.geometry, self.properties, self.players),
            BattleStructure.PLAYERS: (self.players,),
            BattleStructure.UNITS: (self.geometry, self.players, self.units),
        }
        return not self.live_reasons and all(
            result.status is ValidationStatus.VALID for result in dependencies[structure]
        )

    @property
    def can_decode_live(self) -> bool:
        return all(self.available(structure) for structure in BattleStructure)

    def require_live(self) -> None:
        """Fail closed before a consumer decodes the full supported battle subset."""
        reasons = list(self.live_reasons)
        for structure in BattleStructure:
            result: StructureValidation = getattr(self, structure.value)
            if result.status is not ValidationStatus.VALID:
                details = result.reasons or (result.status.value,)
                reasons.extend(f"{structure.value}: {reason}" for reason in details)
        if reasons:
            raise ValueError("Battle data unavailable: " + "; ".join(reasons))


def _result(errors: list[str], unknown: list[str], count: int | None = None) -> StructureValidation:
    if errors:
        return StructureValidation(ValidationStatus.INVALID, tuple(errors + unknown), count)
    if unknown:
        return StructureValidation(ValidationStatus.UNKNOWN, tuple(unknown), count)
    return StructureValidation(ValidationStatus.VALID, count=count)


def _lifecycle(snapshot: BattleMemorySnapshot) -> LifecycleAssessment:
    pool = snapshot.read(0x0200D610, 32 * 0x6C)
    return classify_lifecycle(
        snapshot.u32(0x030040D0),
        snapshot.u32(0x030040EC),
        (unpack_from("<I", pool, index * 0x6C)[0] for index in range(32)),
        battle_control=BattleControlObservation(
            mode=snapshot.u32(0x03003F3C),
            state=snapshot.u16(0x030032D8),
            lock_count=snapshot.read(0x030030F0, 1)[0],
            input_gate=int.from_bytes(snapshot.read(0x030040E4, 2), "little", signed=True),
            input_state=snapshot.u16(0x03003334),
        ),
    )


def _geometry(snapshot: BattleMemorySnapshot) -> StructureValidation:
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    cells = width * height
    if not width or not height:
        return StructureValidation(
            ValidationStatus.INVALID, ("Map dimensions are not initialized",)
        )
    if not (1 <= width <= MAX_WIDTH and 1 <= height <= MAX_HEIGHT and cells <= MAX_CELLS):
        return StructureValidation(
            ValidationStatus.UNKNOWN, ("Dimensions are outside the supported retail envelope",)
        )
    errors: list[str] = []
    unknown: list[str] = []
    for y in range(height):
        if snapshot.u16(MAP_BASE + 0x417A + 2 * y) != y * width:
            errors.append(f"Row {y} does not have the verified packed row offset")
    for index in range(cells):
        tile = snapshot.u16(MAP_BASE + 0x0A22 + 2 * index)
        terrain = snapshot.read(MAP_BASE + 0x1432 + index, 1)[0]
        if tile >= len(snapshot.layout.terrain_by_tile):
            errors.append(f"Cell {index} has a graphical tile outside the ROM lookup")
        elif snapshot.layout.terrain_by_tile[tile] != terrain:
            errors.append(f"Cell {index} disagrees with the ROM tile/terrain lookup")
        if tile > MAX_TILE_ID or terrain & 31 not in TERRAIN_CLASSES:
            unknown.append(f"Cell {index} uses an unsupported tile or terrain class")
        if terrain >> 5 > 4 or (terrain >> 5 and terrain & 31 not in FEATURE_CLASSES):
            errors.append(f"Cell {index} has an invalid terrain owner")
    return _result(errors, unknown, cells)


def _properties(
    snapshot: BattleMemorySnapshot, geometry: StructureValidation
) -> StructureValidation:
    if geometry.status is not ValidationStatus.VALID:
        return StructureValidation(ValidationStatus.UNKNOWN, ("Map geometry is not validated",))
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    errors: list[str] = []
    seen: set[tuple[int, int]] = set()
    count = 0
    for slot in range(PROPERTY_SLOTS):
        terrain, x, y, _ = snapshot.read(PROPERTY_BASE + slot * 4, 4)
        if terrain == 0xFF:
            break
        if terrain == 0:
            continue
        count += 1
        if not (x < width and y < height):
            errors.append(f"Property slot {slot} has coordinates outside the map")
            continue
        if (x, y) in seen:
            errors.append(f"Property slot {slot} duplicates a coordinate")
        seen.add((x, y))
        if terrain & 31 not in FEATURE_CLASSES:
            errors.append(f"Property slot {slot} is not a supported property/feature")
        actual = snapshot.read(MAP_BASE + 0x1432 + y * width + x, 1)[0]
        if terrain != actual:
            errors.append(f"Property slot {slot} disagrees with terrain ownership/type")
        owner = terrain >> 5
        if 1 <= owner <= 4 and snapshot.read(PLAYER_BASE + owner * PLAYER_STRIDE + 0x1B, 1)[0] == 0:
            errors.append(f"Property slot {slot} belongs to an inactive player")
    else:
        errors.append("No property sentinel found within the 92-slot bound")
    expected = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if snapshot.read(MAP_BASE + 0x1432 + y * width + x, 1)[0] & 31 in FEATURE_CLASSES
    }
    if seen != expected:
        errors.append("Property list does not cover the map's properties/features exactly")
    return _result(errors, [], count)


def _players(snapshot: BattleMemorySnapshot) -> StructureValidation:
    errors: list[str] = []
    unknown: list[str] = []
    participants: set[int] = set()
    for slot in range(1, 5):
        record = snapshot.read(PLAYER_BASE + slot * PLAYER_STRIDE, PLAYER_STRIDE)
        if record[0x1B] == 0:
            continue  # Inactive records can retain arbitrary data.
        participants.add(slot)
        if record[0x1B] not in (1, 2):
            unknown.append(f"Player {slot} has an unsupported control type")
        if record[0x1A] != slot:
            errors.append(f"Player {slot} has an inconsistent slot/color ID")
        if record[0x1D] > 18:
            unknown.append(f"Player {slot} has an unsupported CO ID")
        if record[0x1E] > 2 or record[0x2A] > 3:
            errors.append(f"Player {slot} has an invalid active-power/team value")
    if not participants or snapshot.u16(0x030033EC) not in participants:
        errors.append("Turn selector does not identify a participating player")
    if snapshot.u16(0x03004080) == 0:
        errors.append("Battle day is not initialized")
    return _result(errors, unknown, len(participants))


def _units(snapshot: BattleMemorySnapshot, geometry: StructureValidation) -> StructureValidation:
    if geometry.status is not ValidationStatus.VALID:
        return StructureValidation(ValidationStatus.UNKNOWN, ("Map geometry is not validated",))
    width, height = snapshot.u16(MAP_BASE), snapshot.u16(MAP_BASE + 2)
    errors: list[str] = []
    unknown: list[str] = []
    cargo: dict[int, tuple[int, ...]] = {}
    passengers: set[int] = set()
    count = 0
    for army in range(4):
        for slot in range(64):
            index = army * 64 + slot
            record = snapshot.read(UNIT_BASE + index * UNIT_STRIDE, UNIT_STRIDE)
            if not record[0]:
                continue  # Destroyed/empty slots retain stale coordinates and flags.
            count += 1
            if not 1 <= slot <= UNITS_PER_ARMY:
                unknown.append(f"Unit {index} occupies a slot outside the researched allocator")
            if record[0] not in UNIT_TYPES:
                unknown.append(f"Unit {index} has an unsupported type")
            if snapshot.read(PLAYER_BASE + (army + 1) * PLAYER_STRIDE + 0x1B, 1)[0] == 0:
                errors.append(f"Unit {index} belongs to an inactive player")
            if record[2] >= width or record[3] >= height:
                errors.append(f"Unit {index} has coordinates outside the map")
            if not 1 <= record[4] & 0x7F <= 100:
                errors.append(f"Unit {index} has invalid masked health")
            if record[5] >> 3 >= 20:
                errors.append(f"Unit {index} has unsettled or invalid capture progress")
            refs = tuple(ref for ref in record[7:9] if ref)
            if refs and record[0] not in (7, 23):
                unknown.append(f"Unit {index} uses unverified transport/link fields")
                continue
            if record[0] == 7 and record[8]:
                errors.append(f"APC {index} has a second passenger reference")
            cargo[index] = refs
            for ref in refs:
                if ref // 64 != army or not 1 <= ref % 64 <= UNITS_PER_ARMY or ref == index:
                    errors.append(f"Unit {index} has an invalid passenger index {ref}")
                    continue
                if not snapshot.read(UNIT_BASE + ref * UNIT_STRIDE, 1)[0]:
                    errors.append(f"Unit {index} references an empty passenger slot")
                if ref in passengers:
                    errors.append(f"Passenger {ref} is referenced more than once")
                passengers.add(ref)
    visited: set[int] = set()

    def has_cycle(index: int, ancestors: frozenset[int]) -> bool:
        if index in ancestors:
            return True
        if index in visited:
            return False
        visited.add(index)
        return any(has_cycle(ref, ancestors | {index}) for ref in cargo.get(index, ()))

    for start in cargo:
        if has_cycle(start, frozenset()):
            errors.append(f"Cargo references contain a cycle at unit {start}")
    return _result(errors, unknown, count)


def validate_battle_snapshot(snapshot: BattleMemorySnapshot) -> BattleValidationReport:
    """Report raw consistency separately from permission to decode live fields."""
    lifecycle = _lifecycle(snapshot)
    geometry = _geometry(snapshot)
    players = _players(snapshot)
    properties = _properties(snapshot, geometry)
    units = _units(snapshot, geometry)
    live_reasons: list[str] = []
    if lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
        live_reasons.append(
            f"Lifecycle phase {lifecycle.phase.value} is not an allowed live context"
        )
    else:
        turn = snapshot.u16(0x030033EC)
        if not 1 <= turn <= 4:
            live_reasons.append("The selected player is outside the bounded player table")
        elif snapshot.u16(PLAYER_BASE + turn * PLAYER_STRIDE + 0x14) != 0:
            live_reasons.append("The selected player is marked defeated")
    return BattleValidationReport(
        snapshot.frame, lifecycle, geometry, properties, players, units, tuple(live_reasons)
    )
