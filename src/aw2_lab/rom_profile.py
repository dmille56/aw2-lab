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


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a ROM without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as rom_file:
        for chunk in iter(lambda: rom_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
