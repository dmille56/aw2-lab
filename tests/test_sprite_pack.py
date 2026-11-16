"""Static atlas packaging checks; real graphics acceptance requires explicit opt-in."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from aw2_lab.aw2_rules_data import UNIT_DATA
from aw2_lab.rom_profile import UnsupportedRomError
from aw2_lab.sprite_extraction import terrain_sample
from aw2_lab.sprite_pack import TERRAIN_CLASSES, build_sprite_pack, terrain_frame
from aw2_lab.state_validation import TERRAIN_CLASSES as DECODED_TERRAIN_CLASSES


def test_pack_covers_the_decoded_terrain_contract() -> None:
    assert set(TERRAIN_CLASSES) == DECODED_TERRAIN_CLASSES


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
    manifest = build_sprite_pack(rom, tmp_path)
    assert set(manifest["units"]) == {
        f"{unit}:{army}" for unit in UNIT_DATA for army in range(1, 6)
    }
    assert set(manifest["terrain"]) == {
        f"{terrain}:{army}" for terrain in DECODED_TERRAIN_CLASSES for army in range(6)
    }
    for region in [*manifest["units"].values(), *manifest["terrain"].values()]:
        assert 0 <= region["x"] <= manifest["width"] - region["width"]
        assert 0 <= region["y"] <= manifest["height"] - region["height"]
    png = (tmp_path / manifest["atlas"]).read_bytes()
    assert hashlib.sha256(png).hexdigest() == manifest["atlas_sha256"]
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert build_sprite_pack(rom, tmp_path) == manifest
    assert hashlib.sha256(rom.read_bytes()).hexdigest() == before
