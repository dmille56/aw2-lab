"""Audit factual combat tables against a supported local ROM; never write ROM bytes."""

from pathlib import Path
from struct import unpack_from

from aw2_lab.aw2_combat_data import (
    BASE_DAMAGE,
    CO_COMBAT,
    CO_COMBAT_GROUPS,
    TERRAIN_STARS,
    UNIT_COMBAT_GROUPS,
)
from aw2_lab.rom_profile import select_rom_profile


def audit_combat_rules(rom_path: Path) -> int:
    select_rom_profile(rom_path)
    rom = rom_path.read_bytes()
    checks = 0

    def check(expected: object, actual: object) -> None:
        nonlocal checks
        checks += 1
        if expected != actual:
            raise ValueError("Combat facts differ from the supported cartridge")

    for unit, weapons in BASE_DAMAGE.items():
        entry = 0x5D5ABC + unit * 0x5C
        check(UNIT_COMBAT_GROUPS[unit], rom[entry + 0x18])
        for weapon, offset in (("primary", 0x1E), ("secondary", 0x38)):
            for target in range(1, 26):
                check(weapons[weapon].get(target, 0), rom[entry + offset + target])
    for key, values in CO_COMBAT.items():
        co_id, power = map(int, key.split(":"))
        entry = 0x5D3DD0 + co_id * 0x104 + power * 0x44
        check(values[:2], unpack_from("<hh", rom, entry + 0x46))
        check(values[2], unpack_from("<I", rom, entry + 0x40)[0])
        for group, stats in enumerate(CO_COMBAT_GROUPS[key]):
            pointer = unpack_from("<I", rom, entry + 0x5C + group * 4)[0] - 0x08000000
            check(stats, unpack_from("<hh", rom, pointer))
    for terrain, stars in enumerate(TERRAIN_STARS):
        check(stars, unpack_from("<I", rom, 0x5D583C + terrain * 20 + 16)[0])
    return checks
