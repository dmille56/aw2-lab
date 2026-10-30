"""Audit the factual rules catalog against a user-supplied supported ROM.

Run: python -m aw2_lab.unit_rules_audit --rom /local/aw2.gba
No ROM bytes or damage amounts are written to the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from struct import unpack_from

from aw2_lab.aw2_rules_data import CO_FUEL_DISCOUNTS, TERRAIN_NAMES
from aw2_lab.aw2_unit_profiles import (
    UNIT_PROFILES,
    MovementType,
    RuleContext,
    movement_cost,
)
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.state_model import Weather
from aw2_lab.state_validation import UNIT_TYPES

_UNIT_TABLE = 0x5D5ABC
_UNIT_STRIDE = 0x5C
_CO_TABLE = 0x5D3DD0
_CO_STRIDE = 0x104
_POWER_STRIDE = 0x44


def audit_rules(rom_path: Path) -> dict[str, int | str]:
    """Compare every unit, terrain cost, and CO movement/range selection."""
    profile = select_rom_profile(rom_path)
    rom = rom_path.read_bytes()
    if set(UNIT_PROFILES) != UNIT_TYPES:
        raise ValueError("Unit profile coverage differs from validated unit IDs")
    if set(TERRAIN_NAMES) != set(range(32)):
        raise ValueError("Terrain catalog must cover all 32 table indices")
    checks = 0

    def check(expected: object, actual: object, label: str) -> None:
        nonlocal checks
        checks += 1
        if expected != actual:
            raise ValueError(f"Rule mismatch: {label}: ROM={expected!r}, catalog={actual!r}")

    def pointer(offset: int) -> int:
        value = int(unpack_from("<I", rom, offset)[0]) - 0x08000000
        if not 0 <= value < len(rom) - 8:
            raise ValueError(f"Invalid table pointer at {offset:#x}")
        return value

    for unit_type, unit in UNIT_PROFILES.items():
        offset = _UNIT_TABLE + _UNIT_STRIDE * unit_type
        check(
            tuple(rom[offset + index] for index in (0x19, 0xA, 0xB, 0xC, 0xE, 0xF, 0x10)),
            (
                unit.movement_type,
                unit.movement,
                unit.ammo_capacity,
                unit.vision,
                unit.minimum_range,
                unit.maximum_range,
                unit.fuel_capacity,
            ),
            f"unit {unit_type} scalar fields",
        )
        check(unpack_from("<H", rom, offset + 6)[0] * 10, unit.cost, f"unit {unit_type} cost")
        upkeep = pointer(offset + 0x58)
        for terrain in TERRAIN_NAMES:
            check(rom[upkeep + terrain], unit.daily_fuel, f"unit {unit_type} upkeep/{terrain}")
        check(
            bool(rom[offset + 0x1A] & 0x30),
            unit.destroyed_at_zero_fuel,
            f"unit {unit_type} zero fuel loss",
        )
        for table_offset, targets in (
            (0x1E, unit.primary_targets),
            (0x38, unit.secondary_targets),
        ):
            check(
                frozenset(target for target in range(1, 26) if rom[offset + table_offset + target]),
                targets,
                f"unit {unit_type} weapon table {table_offset:#x}",
            )

    for co_id in range(19):
        for power in range(3):
            base = _CO_TABLE + co_id * _CO_STRIDE + power * _POWER_STRIDE
            context = RuleContext(co_id, power)
            flags = int(unpack_from("<I", rom, base + 0x40)[0])
            check(
                2 if flags & 0x80 else 0,
                CO_FUEL_DISCOUNTS.get((co_id, power), 0),
                f"CO {co_id}/{power} air upkeep discount",
            )
            for weather_index, weather in enumerate((Weather.CLEAR, Weather.SNOW, Weather.RAIN)):
                table = pointer(base + 0x50 + weather_index * 4)
                for movement_type in MovementType:
                    for terrain in TERRAIN_NAMES:
                        raw = rom[table + movement_type * 32 + terrain]
                        check(
                            None if raw == 255 else raw,
                            movement_cost(terrain, movement_type, weather, context=context),
                            f"CO {co_id}/{power}/{weather}, movement {movement_type}, terrain {terrain}",
                        )
            for unit_type, unit in UNIT_PROFILES.items():
                offset = _UNIT_TABLE + unit_type * _UNIT_STRIDE
                group = rom[offset + 0x18]
                move, attack_range = unpack_from("<hh", rom, pointer(base + 0x5C + group * 4) + 4)
                if group:
                    category = 6 if unit.indirect else 5 if unit.minimum_range else 7
                    extra_move, extra_range = unpack_from(
                        "<hh", rom, pointer(base + 0x5C + category * 4) + 4
                    )
                    move += extra_move
                    attack_range += extra_range
                check(
                    (unit.movement + move, unit.maximum_range + attack_range),
                    context.unit_limits(unit_type),
                    f"CO {co_id}/{power}, unit {unit_type} movement/range",
                )
    return {
        "rom_sha256": profile.sha256,
        "units": len(UNIT_PROFILES),
        "terrain_ids": len(TERRAIN_NAMES),
        "movement_types": len(MovementType),
        "co_power_states": 19 * 3,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(audit_rules(args.rom.expanduser().resolve()), indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(report)
    print(report, end="")


if __name__ == "__main__":
    main()
