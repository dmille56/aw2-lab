"""Static atlas packaging checks; real graphics acceptance requires explicit opt-in."""

import hashlib
import json
import os
import struct
from collections import Counter
from pathlib import Path

import pytest

from aw2_lab.aw2_rules_data import UNIT_DATA
from aw2_lab.map_catalog import ALL_MAPS
from aw2_lab.rom_profile import UnsupportedRomError
from aw2_lab.sprite_extraction import (
    compose_tiles,
    decode_lz77,
    decode_palette,
    decode_tile,
    terrain_sample,
)
from aw2_lab.sprite_pack import (
    TERRAIN_CLASSES,
    TERRAIN_VARIANT_CLASSES,
    build_sprite_pack,
    terrain_frame,
    terrain_variant_frame,
)
from aw2_lab.state_validation import TERRAIN_CLASSES as DECODED_TERRAIN_CLASSES

# Built-in Versus map headers verified in docs/AW2-MAP-RESEARCH.org: the ROM holds
# 0x5C-byte headers at 0x085C77A0 + map_id * 0x5C whose first word points at the
# compressed cell array. Each decompressed array starts with the byte width and
# height, then one little-endian graphical tile ID per cell.
MAP_HEADER_BASE = 0x085C77A0 - 0x08000000
MAP_HEADER_STRIDE = 0x5C


def built_in_map_cells(rom: bytes, map_id: int) -> tuple[int, int, tuple[int, ...]]:
    """Return a built-in map's width, height, and per-cell graphical tile IDs."""
    header = rom[MAP_HEADER_BASE + map_id * MAP_HEADER_STRIDE :][:8]
    pointer = int.from_bytes(header[:4], "little")
    if not 0x08000000 <= pointer < 0x08800000:
        raise ValueError(f"Map {map_id} header does not point into the ROM")
    cells = decode_lz77(rom, pointer - 0x08000000, maximum_size=65536)
    width, height = cells[0], cells[1]
    if len(cells) != 2 + width * height * 2:
        raise ValueError(f"Map {map_id} cell array does not match its dimensions")
    return width, height, struct.unpack_from(f"<{width * height}H", cells, 2)


def test_pack_covers_the_decoded_terrain_contract() -> None:
    assert set(TERRAIN_CLASSES) == DECODED_TERRAIN_CLASSES


def test_every_variant_bearing_terrain_class_is_packed() -> None:
    assert TERRAIN_VARIANT_CLASSES == (1, 2, 3, 4, 5, 7, 12, 13, 15, 16, 19)
    # City, headquarters, and other property artwork is chosen per army, so its cells
    # cannot be keyed by graphical tile ID alone.
    assert not set(TERRAIN_VARIANT_CLASSES) & {6, 8, 10, 11, 14, 17, 18}


def test_pack_rejects_unknown_rom_before_writing(tmp_path: Path) -> None:
    rom = tmp_path / "unsupported.gba"
    rom.write_bytes(bytes(256))
    output = tmp_path / "pack"
    with pytest.raises(UnsupportedRomError):
        build_sprite_pack(rom, output)
    assert not output.exists()


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_SPRITE_ACCEPTANCE") != "1" or not os.environ.get("AW2_ROM_PATH"),
    reason="requires explicit opt-in and a supported local ROM",
)
def test_local_pack_is_complete_deterministic_and_preserves_rom(tmp_path: Path) -> None:
    rom = Path(os.environ["AW2_ROM_PATH"])
    before = hashlib.sha256(rom.read_bytes()).hexdigest()
    _, _, sea = terrain_frame(rom.read_bytes(), 7, 0)
    assert sea[16 * 16 * 4 :] == terrain_sample(rom.read_bytes(), 42)[2]
    assert sea[16 * 16 * 4 :] != terrain_sample(rom.read_bytes(), 8)[2]
    source = rom.read_bytes()
    expected_variants = {
        f"{value & 31}:{tile}"
        for tile, value in enumerate(source[0x0C1BC4:0x0C1FC4])
        if value & 31 in TERRAIN_VARIANT_CLASSES
    }
    manifest = build_sprite_pack(rom, tmp_path)
    assert set(manifest["terrain_variants"]) == expected_variants
    assert len(expected_variants) == 248
    shoals = [int(key.split(":")[1]) for key in expected_variants if key.startswith("13:")]
    assert len(shoals) == 36
    assert len({terrain_variant_frame(source, tile)[2] for tile in shoals}) >= 4
    plains = [int(key.split(":")[1]) for key in expected_variants if key.startswith("1:")]
    assert len(plains) == 11
    assert len({terrain_variant_frame(source, tile)[2] for tile in plains}) >= 4
    roads = [int(key.split(":")[1]) for key in expected_variants if key.startswith("5:")]
    assert len(roads) == 40
    assert len({terrain_variant_frame(source, tile)[2] for tile in roads}) >= 4
    woods = [int(key.split(":")[1]) for key in expected_variants if key.startswith("4:")]
    assert len(woods) == 19
    assert len({terrain_variant_frame(source, tile)[2] for tile in woods}) == 19
    mountains = sorted(int(key.split(":")[1]) for key in expected_variants if key.startswith("3:"))
    assert mountains == [2, 32, 34, 35]
    assert len({terrain_variant_frame(source, tile)[2] for tile in mountains}) == 4
    for key in expected_variants:
        tile = int(key.split(":")[1])
        width, height, frame = terrain_variant_frame(source, tile)
        assert (width, height) == (16, 32)
        assert frame[:1024] == bytes(1024)
        assert frame[1024:] == terrain_sample(source, tile)[2]
    assert set(manifest["units"]) == {
        f"{unit}:{army}" for unit in UNIT_DATA for army in range(1, 6)
    }
    assert set(manifest["terrain"]) == {
        f"{terrain}:{army}" for terrain in DECODED_TERRAIN_CLASSES for army in range(6)
    }
    assert set(manifest["portraits"]) == {str(co_id) for co_id in range(19)}
    assert all(
        region["width"] == 48 and region["height"] == 48
        for region in manifest["portraits"].values()
    )
    for region in [
        *manifest["units"].values(),
        *manifest["terrain"].values(),
        *manifest["portraits"].values(),
        *manifest["terrain_variants"].values(),
    ]:
        assert 0 <= region["x"] <= manifest["width"] - region["width"]
        assert 0 <= region["y"] <= manifest["height"] - region["height"]
    png = (tmp_path / manifest["atlas"]).read_bytes()
    assert hashlib.sha256(png).hexdigest() == manifest["atlas_sha256"]
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert build_sprite_pack(rom, tmp_path) == manifest
    assert hashlib.sha256(rom.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("tile", [-1, 1024])
def test_terrain_variant_frame_rejects_invalid_graphical_ids(tile: int) -> None:
    with pytest.raises(ValueError, match="verified per-cell terrain graphical tile"):
        terrain_variant_frame(b"", tile)


def test_synthetic_rom_packs_mountain_variants_with_native_composition() -> None:
    """ROM-free check that each mountain cell keeps its own metatile, palette, and flips."""
    rom = bytearray(0x0CABC4)
    graphics = bytearray(8192)
    for tile, index in ((4, 1), (5, 5), (36, 6), (37, 7), (68, 8), (69, 9), (100, 10), (101, 11)):
        graphics[tile * 32 : (tile + 1) * 32] = bytes([index * 0x11]) * 32
    # Tile 4 splits horizontally so the flip flags are observable.
    graphics[4 * 32 : 5 * 32] = bytes([0x11, 0x11, 0x22, 0x22]) * 8
    compressed = (
        b"\x10"
        + len(graphics).to_bytes(3, "little")
        + b"".join(b"\0" + graphics[offset : offset + 8] for offset in range(0, 8192, 8))
    )
    rom[0x0BD1EC : 0x0BD1EC + len(compressed)] = compressed
    struct.pack_into("<16H", rom, 0x0BF8C4, *(index * 2 for index in range(16)))
    struct.pack_into("<16H", rom, 0x0BF8C4 + 32, *(31 - index * 2 for index in range(16)))
    for tile, terrain_class in ((1, 1), (2, 3), (3, 3), (4, 3), (6, 6), (8, 8)):
        rom[0x0C1BC4 + tile] = terrain_class
    struct.pack_into("<4H", rom, 0x0BFBC4 + 2 * 8, 4, 5, 36, 37)
    struct.pack_into("<4H", rom, 0x0BFBC4 + 3 * 8, 4 | 1024, 5, 36, 37 | 2048)
    struct.pack_into("<4H", rom, 0x0BFBC4 + 4 * 8, (68 | 4096), 69 | 4096, 100 | 4096, 101 | 4096)
    source = bytes(rom)
    neutral = decode_palette(source, 0x0BF8C4, transparent=False)

    width, height, ground = terrain_variant_frame(source, 2)
    assert (width, height) == (16, 32)
    assert ground[:1024] == bytes(1024)
    assert ground[1024:] == terrain_sample(source, 2)[2]

    def pixel(row: int, column: int) -> tuple[int, int, int, int]:
        offset = ((16 + row) * 16 + column) * 4
        return tuple(ground[offset : offset + 4])

    assert pixel(0, 0) == pixel(0, 3) == neutral[1]
    assert pixel(0, 4) == pixel(0, 7) == neutral[2]
    assert pixel(0, 8) == neutral[5]
    assert pixel(8, 0) == neutral[6]
    assert pixel(8, 8) == neutral[7]

    mirrored = compose_tiles(
        [
            decode_tile(graphics, 4 * 32, neutral, flip_x=True),
            decode_tile(graphics, 5 * 32, neutral),
            decode_tile(graphics, 36 * 32, neutral),
            decode_tile(graphics, 37 * 32, neutral, flip_y=True),
        ],
        2,
    )
    assert terrain_variant_frame(source, 3) == (16, 32, bytes(1024) + mirrored[2])

    army_palette = decode_palette(source, 0x0BF8C4 + 32, transparent=False)
    alternative_ground = terrain_variant_frame(source, 4)[2][1024:]
    assert alternative_ground[:4] == bytes(army_palette[8])
    assert alternative_ground != ground[1024:]

    with pytest.raises(ValueError, match="verified per-cell terrain graphical tile"):
        terrain_variant_frame(source, 8)
    # Property artwork belongs to the army, not to the cell's graphical tile ID.
    with pytest.raises(ValueError, match="verified per-cell terrain graphical tile"):
        terrain_variant_frame(source, 6)


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_SPRITE_ACCEPTANCE") != "1" or not os.environ.get("AW2_ROM_PATH"),
    reason="requires explicit opt-in and a supported local ROM",
)
def test_bean_island_mountain_cells_get_their_native_variants(tmp_path: Path) -> None:
    """Bean Island draws mountains with four shapes; each referenced shape must be packed."""
    rom_path = Path(os.environ["AW2_ROM_PATH"])
    rom = rom_path.read_bytes()
    lookup = rom[0x0C1BC4:0x0C1FC4]
    width, height, cells = built_in_map_cells(rom, 1)  # Bean Island
    assert (width, height) == (16, 15)
    mountain_cells = Counter(tile for tile in cells if lookup[tile] & 31 == 3)
    assert mountain_cells == Counter({34: 19, 35: 6, 2: 5, 32: 3})

    manifest = build_sprite_pack(rom_path, tmp_path)
    assert all(f"3:{tile}" in manifest["terrain_variants"] for tile in mountain_cells)
    representative = terrain_frame(rom, 3, 0)[2]
    distinct_shapes = {
        tile for tile in mountain_cells if terrain_variant_frame(rom, tile)[2] != representative
    }
    assert distinct_shapes == {32, 34, 35}
    assert sum(mountain_cells[tile] for tile in distinct_shapes) == 28

    # Guard against any built-in map cell whose artwork is not packed.
    for entry in ALL_MAPS:
        map_width, map_height, map_cells = built_in_map_cells(rom, entry.rom_id)
        assert (map_width, map_height) == (entry.width, entry.height)
        missing = {
            tile
            for tile in map_cells
            if lookup[tile] & 31 in TERRAIN_VARIANT_CLASSES
            and f"{lookup[tile] & 31}:{tile}" not in manifest["terrain_variants"]
        }
        assert not missing, f"map {entry.id} has unpacked terrain variants: {missing}"


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_SPRITE_ACCEPTANCE") != "1" or not os.environ.get("AW2_ROM_PATH"),
    reason="requires explicit opt-in and a supported local ROM",
)
def test_plains_cells_carry_the_mountain_tip_above_a_range(tmp_path: Path) -> None:
    """A mountain range spills its rocky tip into the plains cell directly above it."""
    rom_path = Path(os.environ["AW2_ROM_PATH"])
    rom = rom_path.read_bytes()
    lookup = rom[0x0C1BC4:0x0C1FC4]
    width, height, cells = built_in_map_cells(rom, 1)  # Bean Island
    plains = {tile for tile in cells if lookup[tile] & 31 == 1}
    assert plains == {1, 33, 67}

    manifest = build_sprite_pack(rom_path, tmp_path)
    assert all(f"1:{tile}" in manifest["terrain_variants"] for tile in plains)

    flat, tip = terrain_variant_frame(rom, 1)[2][1024:], terrain_variant_frame(rom, 67)[2][1024:]
    assert tip != flat
    changed_rows = {
        row
        for row in range(16)
        for column in range(16)
        if tip[(row * 16 + column) * 4 : (row * 16 + column) * 4 + 4]
        != flat[(row * 16 + column) * 4 : (row * 16 + column) * 4 + 4]
    }
    # The tip is the bottom band of the plains cell, touching the mountain cell below it.
    assert changed_rows == set(range(11, 16))
    grid = [[cells[y * width + x] for x in range(width)] for y in range(height)]
    assert grid[2][3] == 67 and lookup[grid[3][3]] & 31 == 3


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_SPRITE_ACCEPTANCE") != "1" or not os.environ.get("AW2_ROM_PATH"),
    reason="requires explicit opt-in and a supported local ROM",
)
def test_every_catalog_map_cell_resolves_to_packed_artwork(tmp_path: Path) -> None:
    """No built-in Versus map cell may fall back to the client's symbolic board."""
    rom_path = Path(os.environ["AW2_ROM_PATH"])
    rom = rom_path.read_bytes()
    lookup = rom[0x0C1BC4:0x0C1FC4]
    manifest = build_sprite_pack(rom_path, tmp_path)
    variants = manifest["terrain_variants"]
    representatives = manifest["terrain"]

    parsed_maps = 0
    cells = 0
    classes: Counter[int] = Counter()
    pipe_tiles: set[int] = set()
    for entry in ALL_MAPS:
        try:
            _, _, tile_ids = built_in_map_cells(rom, entry.rom_id)
        except ValueError:
            continue
        parsed_maps += 1
        for tile_id in tile_ids:
            terrain_class = lookup[tile_id] & 31
            classes[terrain_class] += 1
            cells += 1
            if terrain_class in TERRAIN_VARIANT_CLASSES:
                assert f"{terrain_class}:{tile_id}" in variants, (
                    f"{entry.id} uses unpacked variant {terrain_class}:{tile_id}"
                )
            else:
                assert any(f"{terrain_class}:{army}" in representatives for army in range(6)), (
                    f"{entry.id} has no representative for terrain class {terrain_class}"
                )
            if terrain_class in (15, 16):
                pipe_tiles.add(tile_id)

    assert parsed_maps == len(ALL_MAPS)
    assert cells > 60_000
    assert set(classes) <= set(TERRAIN_CLASSES)
    # Pipes and seams appear only in four-player maps, which the two-player CLI cannot
    # launch yet, so packing every observed pipe cell is the available guarantee.
    packed_pipe_ids = {
        int(key.split(":")[1]) for key in variants if key.split(":")[0] in ("15", "16")
    }
    assert pipe_tiles and pipe_tiles <= packed_pipe_ids
