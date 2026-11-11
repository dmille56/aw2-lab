"""Load supported external save profiles without modifying their source files."""

from __future__ import annotations

from pathlib import Path
from struct import unpack_from

_SHARKPORT_MAGIC = b"SharkPortSave"
_SHARKPORT_HEADER_SIZE = 0x1C
_AW2_SRAM_SIZE = 0x10000


def decode_sharkport_save(source: Path, rom_path: Path) -> bytes:
    """Extract the 64 KiB AW2 SRAM payload from a ROM-matched SharkPort save."""
    data = source.read_bytes()
    offset = 0

    def read_u32(label: str) -> int:
        nonlocal offset
        if offset + 4 > len(data):
            raise ValueError(f"truncated GameShark SP save while reading {label}")
        value = int(unpack_from("<I", data, offset)[0])
        offset += 4
        return value

    magic_length = read_u32("magic length")
    if magic_length != len(_SHARKPORT_MAGIC) or data[offset : offset + magic_length] != (
        _SHARKPORT_MAGIC
    ):
        raise ValueError("save profile is not a SharkPort .sps file")
    offset += magic_length
    if read_u32("container version") != 0x000F0000:
        raise ValueError("unsupported GameShark SP save container version")

    for field_name in ("game title", "timestamp", "comment"):
        field_length = read_u32(f"{field_name} length")
        if field_length > len(data) - offset:
            raise ValueError(f"truncated GameShark SP save {field_name}")
        offset += field_length

    record_length = read_u32("payload record length")
    if record_length < _SHARKPORT_HEADER_SIZE:
        raise ValueError("invalid GameShark SP save payload length")
    payload_length = record_length - _SHARKPORT_HEADER_SIZE
    if payload_length != _AW2_SRAM_SIZE:
        raise ValueError(
            f"expected {_AW2_SRAM_SIZE} bytes of AW2 SRAM in GameShark SP save; "
            f"found {payload_length}"
        )
    end = offset + _SHARKPORT_HEADER_SIZE + payload_length
    if end + 4 != len(data):
        raise ValueError("GameShark SP save has a truncated payload or unexpected trailing data")

    save_header = data[offset : offset + _SHARKPORT_HEADER_SIZE]
    with rom_path.open("rb") as rom_file:
        rom_file.seek(0xA0)
        rom_identity = rom_file.read(16)
    if len(rom_identity) != 16 or save_header[:16] != rom_identity:
        raise ValueError("GameShark SP save belongs to a different ROM")
    return data[offset + _SHARKPORT_HEADER_SIZE : end]
