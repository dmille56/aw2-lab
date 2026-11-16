"""ROM-independent graphics decoding checks; live extraction is explicitly opt-in."""

import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from aw2_lab.rom_profile import UnsupportedRomError
from aw2_lab.sprite_extraction import (
    compose_tiles,
    decode_lz77,
    decode_palette,
    decode_tile,
    encode_png,
    extract_samples,
)


def test_lz77_literals_and_overlapping_back_reference() -> None:
    # Three literals followed by six bytes copied from three bytes back.
    assert decode_lz77(b"\x10\x09\0\0\x10ABC\x30\x02", 0) == b"ABCABCABC"


@pytest.mark.parametrize(
    "data",
    [b"", b"\x11\0\0\0", b"\x10\0\0\0", b"\x10\x01\0\0", b"\x10\x03\0\0\x80\0\0"],
)
def test_lz77_rejects_malformed_graphics(data: bytes) -> None:
    with pytest.raises(ValueError):
        decode_lz77(data, 0)


def test_lz77_rejects_oversized_output() -> None:
    with pytest.raises(ValueError, match="allowed size"):
        decode_lz77(b"\x10\xff\xff\xff", 0)


def test_palette_channels_and_transparent_index() -> None:
    raw = struct.pack("<16H", 0, 31, 31 << 5, 31 << 10, *([0] * 12))
    palette = decode_palette(raw, 0, transparent=True)
    assert palette[:4] == ((0, 0, 0, 0), (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))
    assert decode_palette(raw, 0, transparent=False)[0] == (0, 0, 0, 255)
    with pytest.raises(ValueError, match="Truncated"):
        decode_palette(raw[:-1], 0, transparent=True)


def test_tile_nibbles_and_flips() -> None:
    palette = tuple((i, i, i, 255) for i in range(16))
    data = bytes([0x21, 0x43, 0x65, 0x87]) + bytes(28)
    pixels = decode_tile(data, 0, palette)
    assert pixels[:8] == bytes((1, 1, 1, 255, 2, 2, 2, 255))
    assert decode_tile(data, 0, palette, flip_x=True)[:4] == bytes((8, 8, 8, 255))
    assert decode_tile(data, 0, palette, flip_y=True)[-32:] == pixels[:32]
    with pytest.raises(ValueError):
        decode_tile(data[:-1], 0, palette)


def test_composition_and_png_pixels() -> None:
    left, right = bytes((255, 0, 0, 255)) * 64, bytes((0, 255, 0, 255)) * 64
    width, height, pixels = compose_tiles([left, right], 2)
    assert (width, height) == (16, 8)
    assert pixels[:64] == left[:32] + right[:32]
    png = encode_png(width, height, pixels)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    cursor, image_data = 8, bytearray()
    while cursor < len(png):
        length = int.from_bytes(png[cursor : cursor + 4], "big")
        kind = png[cursor + 4 : cursor + 8]
        payload = png[cursor + 8 : cursor + 8 + length]
        assert zlib.crc32(kind + payload) == int.from_bytes(
            png[cursor + 8 + length : cursor + 12 + length], "big"
        )
        if kind == b"IDAT":
            image_data.extend(payload)
        cursor += length + 12
    assert zlib.decompress(image_data) == b"".join(
        b"\0" + pixels[y * 64 : (y + 1) * 64] for y in range(height)
    )


def test_unsupported_rom_creates_no_output(tmp_path: Path) -> None:
    rom = tmp_path / "unsupported.gba"
    rom.write_bytes(bytes(256))
    output = tmp_path / "samples"
    with pytest.raises(UnsupportedRomError):
        extract_samples(rom, output)
    assert not output.exists()


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_SPRITE_ACCEPTANCE") != "1" or not os.environ.get("AW2_ROM_PATH"),
    reason="requires explicit opt-in and a supported local ROM",
)
def test_local_rom_sample_extraction(tmp_path: Path) -> None:
    rom = Path(os.environ["AW2_ROM_PATH"])
    before = rom.read_bytes()
    extract_samples(rom, tmp_path)
    manifest = json.loads((tmp_path / "samples.json").read_text())
    assert len(manifest["samples"]) == 30
    assert manifest["samples"]["city-army-0.png"] == {"width": 16, "height": 24}
    assert all(
        (tmp_path / name).read_bytes().startswith(b"\x89PNG") for name in manifest["samples"]
    )
    assert rom.read_bytes() == before
