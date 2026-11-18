"""Build an external, static client atlas from the supported local AW2 ROM."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypedDict

from aw2_lab.aw2_rules_data import UNIT_DATA
from aw2_lab.rom_profile import select_rom_profile
from aw2_lab.sprite_extraction import (
    co_portrait_sample,
    compose_tiles,
    decode_palette,
    decode_tile,
    encode_png,
    terrain_sample,
    unit_sample,
)

TERRAIN_CLASSES = tuple(range(1, 9)) + tuple(range(10, 20))
# Terrain classes whose artwork varies per map cell rather than per army. Mountain,
# woods, road, sea, and shoal cells reference distinct graphical tile IDs whose
# four-tile composition, palette index, or flips differ from the class
# representative.
TERRAIN_VARIANT_CLASSES = (3, 4, 5, 7, 13)
# Sources selected by the original terrain information renderer at 0x0803F6BC.
PROPERTY_SOURCES = {
    6: (0x0CFFC4 + 0x440, 6),
    10: (0x0CFFC4 + 0x140, 6),
    11: (0x0CFFC4 + 0x240, 6),
    14: (0x0CFFC4 + 0x80, 4),
    17: (0x0CFFC4 + 0xA40, 6),
    18: (0x0CFFC4 + 0xB00, 4),
}


class Region(TypedDict):
    x: int
    y: int
    width: int
    height: int


class SpriteManifest(TypedDict):
    kind: str
    version: int
    rom_sha256: str
    atlas: str
    atlas_sha256: str
    width: int
    height: int
    units: dict[str, Region]
    terrain: dict[str, Region]
    portraits: dict[str, Region]
    terrain_variants: dict[str, Region]


def property_frame(rom: bytes, terrain: int, army: int) -> tuple[int, int, bytes]:
    if terrain == 8:
        offset, count = 0x0D16C4 + max(0, army - 1) * 256, 8
    else:
        offset, count = PROPERTY_SOURCES[terrain]
    palette = decode_palette(rom, 0x0D3EE4 + army * 32, transparent=True)
    return compose_tiles([decode_tile(rom, offset + i * 32, palette) for i in range(count)], 2)


def terrain_frame(rom: bytes, terrain: int, army: int) -> tuple[int, int, bytes]:
    tile = next(
        (i for i, value in enumerate(rom[0x0C1BC4:0x0C1FC4]) if value & 31 == terrain),
        None,
    )
    if tile is None:
        raise ValueError(f"No verified graphical tile for terrain {terrain}")
    # The first sea entry (8) is a tiny island/shore transition. Use the
    # interior water tile observed at Bean Island (0,0), not a repeated coast.
    if terrain == 7:
        tile = 42
        if rom[0x0C1BC4 + tile] & 31 != terrain:
            raise ValueError("Representative sea tile does not match the terrain lookup")
    _, _, ground = terrain_sample(rom, tile)
    result = bytearray(16 * 32 * 4)
    result[16 * 16 * 4 :] = ground
    if terrain in PROPERTY_SOURCES or terrain == 8:
        _, height, foreground = property_frame(rom, terrain, army)
        for y in range(height):
            for x in range(16):
                source = (y * 16 + x) * 4
                destination = ((32 - height + y) * 16 + x) * 4
                if foreground[source + 3]:
                    result[destination : destination + 4] = foreground[source : source + 4]
    return 16, 32, bytes(result)


def terrain_variant_frame(rom: bytes, graphical_tile_id: int) -> tuple[int, int, bytes]:
    """Keep native mountain/woods/road/water/shoal composition, orientation, and flips."""
    if not 0 <= graphical_tile_id < 1024 or rom[0x0C1BC4 + graphical_tile_id] & 31 not in (
        TERRAIN_VARIANT_CLASSES
    ):
        raise ValueError("Expected a verified mountain, woods, road, sea, or shoal graphical tile")
    _, _, ground = terrain_sample(rom, graphical_tile_id)
    return 16, 32, bytes(16 * 16 * 4) + ground


def build_sprite_pack(rom_path: Path, output: Path) -> SpriteManifest:
    profile = select_rom_profile(rom_path)
    output = output.expanduser().resolve()
    project = Path(__file__).resolve().parents[2]
    if output.is_relative_to(project) or output.is_relative_to(Path("/nix/store")):
        raise ValueError("Generated artwork must be outside the repository and Nix store")
    rom = rom_path.read_bytes()
    frames: list[tuple[str, str, tuple[int, int, bytes]]] = []
    for unit in sorted(UNIT_DATA):
        for army in range(1, 6):
            frames.append(("units", f"{unit}:{army}", unit_sample(rom, unit, army)))
    for terrain in TERRAIN_CLASSES:
        for army in range(6):
            frames.append(("terrain", f"{terrain}:{army}", terrain_frame(rom, terrain, army)))
    map_count = len(frames)
    map_height = ((map_count + 15) // 16) * 32
    for co_id in range(19):
        frames.append(("portraits", str(co_id), co_portrait_sample(rom, co_id)))
    variant_ids = [
        tile
        for tile, value in enumerate(rom[0x0C1BC4:0x0C1FC4])
        if value & 31 in TERRAIN_VARIANT_CLASSES
    ]
    for tile in variant_ids:
        terrain = rom[0x0C1BC4 + tile] & 31
        frames.append(("terrain_variants", f"{terrain}:{tile}", terrain_variant_frame(rom, tile)))
    variants_y = map_height + 4 * 48
    width, height = 256, variants_y + ((len(variant_ids) + 15) // 16) * 32
    pixels = bytearray(width * height * 4)
    units: dict[str, Region] = {}
    terrains: dict[str, Region] = {}
    portraits: dict[str, Region] = {}
    terrain_variants: dict[str, Region] = {}
    collections = {
        "units": units,
        "terrain": terrains,
        "portraits": portraits,
        "terrain_variants": terrain_variants,
    }
    for index, (kind, key, (w, h, frame)) in enumerate(frames):
        if kind == "portraits":
            portrait_index = index - map_count
            x, y = portrait_index % 5 * 48, map_height + portrait_index // 5 * 48
        elif kind == "terrain_variants":
            variant_index = index - map_count - 19
            x, y = variant_index % 16 * 16, variants_y + variant_index // 16 * 32
        else:
            x, y = index % 16 * 16, index // 16 * 32
        for row in range(h):
            start = ((y + row) * width + x) * 4
            pixels[start : start + w * 4] = frame[row * w * 4 : (row + 1) * w * 4]
        collections[kind][key] = {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
        }
    png = encode_png(width, height, bytes(pixels))
    digest = hashlib.sha256(png).hexdigest()
    atlas = f"atlas-{digest}.png"
    manifest: SpriteManifest = {
        "kind": "aw2-client-sprites",
        "version": 1,
        "rom_sha256": profile.sha256,
        "atlas": atlas,
        "atlas_sha256": digest,
        "width": width,
        "height": height,
        "units": units,
        "terrain": terrains,
        "portraits": portraits,
        "terrain_variants": terrain_variants,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / atlas).write_bytes(png)
    temporary = output / ".manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_sprite_pack(args.rom, args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Sprite pack extraction failed: {error}\n")
    print(
        f"Extracted {len(manifest['units'])} unit, {len(manifest['terrain'])} terrain, "
        f"{len(manifest['portraits'])} CO portraits, and {len(manifest['terrain_variants'])} terrain variants"
    )


if __name__ == "__main__":
    main()
