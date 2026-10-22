"""Identity and version metadata for supported Advance Wars 2 ROMs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RomProfile:
    """A verified ROM identity and the versions used to interpret its memory."""

    name: str
    title: str
    game_code: str
    maker_code: str
    revision: int
    sha256: str
    memory_layout_version: str
    decoder_version: str


AW2_US_REVISION_0 = RomProfile(
    name="Advance Wars 2: Black Hole Rising (US) revision 0",
    title="ADVANCEWARS2",
    game_code="AW2E",
    maker_code="01",
    revision=0,
    sha256="ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134",
    memory_layout_version="aw2-us-v1",
    decoder_version="1",
)


class UnsupportedRomError(ValueError):
    """Raised when a ROM does not match a supported, verified image."""


def select_rom_profile(path: Path) -> RomProfile:
    """Select the verified profile for a ROM, rejecting every unknown image."""
    digest = sha256_file(path)
    if digest == AW2_US_REVISION_0.sha256:
        return AW2_US_REVISION_0

    header = _read_header_identity(path)
    detail = f"ROM SHA-256 {digest} is not supported"
    if header is not None:
        title, game_code, maker_code, revision = header
        detail += (
            f" (header title={title!r}, game_code={game_code!r}, "
            f"maker_code={maker_code!r}, revision={revision})"
        )
    detail += f"; supported image: {AW2_US_REVISION_0.name}"
    raise UnsupportedRomError(detail)


def _read_header_identity(path: Path) -> tuple[str, str, str, int] | None:
    """Read the identifying fields from a GBA header when the file is long enough."""
    with path.open("rb") as rom_file:
        rom_file.seek(0xA0)
        header = rom_file.read(0x1D)
    if len(header) < 0x1D:
        return None
    return (
        header[0:12].decode("ascii", errors="replace").rstrip("\x00"),
        header[12:16].decode("ascii", errors="replace"),
        header[16:18].decode("ascii", errors="replace"),
        header[0x1C],
    )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a ROM without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as rom_file:
        for chunk in iter(lambda: rom_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
