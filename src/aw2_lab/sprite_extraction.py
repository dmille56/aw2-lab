"""ROM-local graphics extraction proof; no ROM or generated artwork is packaged.

Run ``python -m aw2_lab.sprite_extraction --rom PATH --output-dir DIRECTORY``.
Offsets below are file offsets for the verified US revision-0 image only.
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

from aw2_lab.rom_profile import select_rom_profile

RGBA = tuple[int, int, int, int]
UNIT_FRAME_BASE = 0x10BE60
UNIT_PALETTE_BASE = 0x10E6E0
UNIT_LOOKUP_BASE = 0x499608
TERRAIN_GRAPHICS_BASE = 0x0BD1EC
TERRAIN_PALETTE_BASE = 0x0BF8C4
TERRAIN_METATILE_BASE = 0x0BFBC4


def decode_lz77(data: bytes, offset: int, *, maximum_size: int = 65536) -> bytes:
    """Decode a bounded GBA BIOS type-0x10 stream, including overlapping copies."""
    if offset < 0 or offset + 4 > len(data) or data[offset] != 0x10:
        raise ValueError("Expected a GBA type-0x10 compression header")
    size = int.from_bytes(data[offset + 1 : offset + 4], "little")
    if not 0 < size <= maximum_size:
        raise ValueError("Decompressed graphics exceed the allowed size")
    result = bytearray()
    cursor = offset + 4
    try:
        while len(result) < size:
            flags = data[cursor]
            cursor += 1
            for bit in range(7, -1, -1):
                if flags & (1 << bit):
                    first, second = data[cursor], data[cursor + 1]
                    cursor += 2
                    length = (first >> 4) + 3
                    distance = ((first & 15) << 8 | second) + 1
                    if distance > len(result) or len(result) + length > size:
                        raise ValueError("Invalid graphics back-reference")
                    for _ in range(length):
                        result.append(result[-distance])
                else:
                    result.append(data[cursor])
                    cursor += 1
                if len(result) == size:
                    break
    except IndexError as error:
        raise ValueError("Truncated compressed graphics") from error
    return bytes(result)


def expand_channel(value: int) -> int:
    """Scale one GBA 5-bit channel to 8 bits the way mGBA displays it.

    ``v * 255 / 31`` rounded down is the obvious conversion, but mGBA's GBA core uses
    ``v << 3 | v >> 2``, which lands one unit higher for most values. Matching the
    emulator exactly is what lets the sprite audit treat any leftover pixel difference
    as real artwork instead of rounding.
    """
    return (value << 3) | (value >> 2)


def decode_palette(data: bytes, offset: int, *, transparent: bool) -> tuple[RGBA, ...]:
    """Read one GBA BGR555 palette; sprite color zero is transparent."""
    if offset < 0 or offset + 32 > len(data):
        raise ValueError("Truncated graphics palette")
    return tuple(
        (
            expand_channel(color & 31),
            expand_channel((color >> 5) & 31),
            expand_channel((color >> 10) & 31),
            0 if transparent and index == 0 else 255,
        )
        for index, color in enumerate(struct.unpack_from("<16H", data, offset))
    )


def decode_tile(
    data: bytes | bytearray,
    offset: int,
    palette: tuple[RGBA, ...],
    *,
    flip_x: bool = False,
    flip_y: bool = False,
) -> bytes:
    """Decode a 4bpp 8x8 tile with the GBA tilemap flip flags."""
    if offset < 0 or offset + 32 > len(data) or len(palette) != 16:
        raise ValueError("Invalid tile graphics or palette")
    pixels = bytearray()
    for y in range(8):
        for x in range(8):
            source_x = 7 - x if flip_x else x
            source_y = 7 - y if flip_y else y
            value = data[offset + source_y * 4 + source_x // 2]
            pixels.extend(palette[(value >> ((source_x % 2) * 4)) & 15])
    return bytes(pixels)


def compose_tiles(tiles: list[bytes], columns: int) -> tuple[int, int, bytes]:
    """Arrange complete 8x8 RGBA tiles in row-major order."""
    if columns < 1 or not tiles or len(tiles) % columns or any(len(t) != 256 for t in tiles):
        raise ValueError("Tile composition requires complete rows of 8x8 tiles")
    width, height = columns * 8, len(tiles) // columns * 8
    pixels = bytearray(width * height * 4)
    for index, tile in enumerate(tiles):
        for y in range(8):
            start = ((index // columns * 8 + y) * width + index % columns * 8) * 4
            pixels[start : start + 32] = tile[y * 32 : (y + 1) * 32]
    return width, height, bytes(pixels)


def encode_png(width: int, height: int, pixels: bytes) -> bytes:
    """Encode deterministic RGBA PNGs without an imaging dependency."""
    if width < 1 or height < 1 or len(pixels) != width * height * 4:
        raise ValueError("PNG dimensions do not match RGBA pixels")

    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            struct.pack(">I", len(content))
            + kind
            + content
            + struct.pack(">I", zlib.crc32(kind + content))
        )

    scanlines = b"".join(b"\0" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


# US rev-0 CO graphics table: 0x44-byte entries, palette +8, compressed neutral portrait +12.
CO_GRAPHICS_TABLE = 0x4A0090


def co_portrait_sample(rom: bytes, co_id: int) -> tuple[int, int, bytes]:
    """Decode the complete neutral 48x48 CO portrait used by the game."""
    if not 0 <= co_id < 19:
        raise ValueError("Unsupported commanding officer portrait")
    entry = CO_GRAPHICS_TABLE + co_id * 0x44
    if entry + 16 > len(rom):
        raise ValueError("Truncated CO graphics table")
    palette_offset = struct.unpack_from("<I", rom, entry + 8)[0] - 0x08000000
    graphics_offset = struct.unpack_from("<I", rom, entry + 12)[0] - 0x08000000
    palette = decode_palette(rom, palette_offset, transparent=True)
    graphics = decode_lz77(rom, graphics_offset, maximum_size=36 * 32)
    if len(graphics) != 36 * 32:
        raise ValueError("Expected a complete 48x48 CO portrait")
    # Native OAM at 0x084A0790 assembles six 48-pixel rows from 32x8 / 16x8 pairs.
    return compose_tiles([decode_tile(graphics, tile * 32, palette) for tile in range(36)], 6)


def unit_sample(rom: bytes, unit_type: int, army: int) -> tuple[int, int, bytes]:
    """First idle frame using the game's per-nation unit lookup (armies 1..5)."""
    if not 1 <= army <= 5 or not 1 <= unit_type <= 24:
        raise ValueError("Unit samples require unit IDs 1..24 and army IDs 1..5")
    index = struct.unpack_from("<H", rom, UNIT_LOOKUP_BASE + (army - 1) * 50 + unit_type * 2)[0]
    palette = decode_palette(rom, UNIT_PALETTE_BASE + (army - 1) * 32, transparent=True)
    return compose_tiles(
        [
            decode_tile(rom, UNIT_FRAME_BASE + index * 128 + tile * 32, palette, flip_x=True)
            for tile in (1, 0, 3, 2)
        ],
        2,
    )


def terrain_sample(rom: bytes, graphical_tile_id: int) -> tuple[int, int, bytes]:
    """Decode the static ground layer with first-frame animated terrain pages."""
    if not 0 <= graphical_tile_id < 1024:
        raise ValueError("Graphical tile ID is outside the supported lookup")
    graphics = bytearray(decode_lz77(rom, TERRAIN_GRAPHICS_BASE))
    graphics[0x2000:0x3000] = rom[0x0C1FC4:0x0C2FC4]
    graphics[0x4000:0x4C00] = rom[0x0C9FC4:0x0CABC4]
    attributes = struct.unpack_from("<4H", rom, TERRAIN_METATILE_BASE + graphical_tile_id * 8)
    return compose_tiles(
        [
            decode_tile(
                graphics,
                (attribute & 1023) * 32,
                decode_palette(
                    rom, TERRAIN_PALETTE_BASE + (attribute >> 12) * 32, transparent=False
                ),
                flip_x=bool(attribute & 1024),
                flip_y=bool(attribute & 2048),
            )
            for attribute in attributes
        ],
        2,
    )


def city_sample(rom: bytes, army: int) -> tuple[int, int, bytes]:
    """City's 16x24 foreground frame, as copied by ROM routine 0x0803F79C."""
    if not 0 <= army <= 5:
        raise ValueError("City palette requires neutral or an army ID 1..5")
    palette = decode_palette(rom, 0x0D3EE4 + army * 32, transparent=True)
    return compose_tiles(
        [decode_tile(rom, 0x0CFFC4 + 0x440 + tile * 32, palette) for tile in range(6)], 2
    )


def extract_samples(rom_path: Path, output: Path) -> None:
    """Write only locally derived PNG samples and reproducibility metadata."""
    profile = select_rom_profile(rom_path)
    output = output.expanduser().resolve()
    project = Path(__file__).resolve().parents[2]
    if output.is_relative_to(project) or output.is_relative_to(Path("/nix/store")):
        raise ValueError("Generated artwork must be outside the repository and Nix store")
    rom = rom_path.read_bytes()
    samples = {
        f"terrain-{name}": terrain_sample(rom, tile)
        for name, tile in (("plain", 1), ("mountain", 2), ("woods", 36), ("sea", 8))
    }
    for army in range(1, 6):
        for unit in (1, 5, 16, 21):
            samples[f"unit-{unit}-army-{army}"] = unit_sample(rom, unit, army)
    for army in range(6):
        samples[f"city-army-{army}"] = city_sample(rom, army)
    output.mkdir(parents=True, exist_ok=True)
    for name, (width, height, pixels) in samples.items():
        (output / f"{name}.png").write_bytes(encode_png(width, height, pixels))
    metadata = {
        "kind": "aw2-sprite-extraction-proof",
        "version": 1,
        "rom_sha256": profile.sha256,
        "samples": {
            f"{name}.png": {"width": w, "height": h} for name, (w, h, _) in samples.items()
        },
        "limitations": [
            "Representative samples only; not a client sprite pack",
            "Clear palette and first animation frames only",
            "Ground layer only; city foreground exported separately",
        ],
    }
    (output / "samples.json").write_text(json.dumps(metadata, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        extract_samples(args.rom, args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Sprite extraction failed: {error}\n")
    print(f"Extracted representative sprites to {args.output_dir}")


if __name__ == "__main__":
    main()
