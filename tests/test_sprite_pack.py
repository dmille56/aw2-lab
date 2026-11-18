"""Static atlas packaging checks; real graphics acceptance requires explicit opt-in."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from aw2_lab.aw2_rules_data import UNIT_DATA
from aw2_lab.rom_profile import UnsupportedRomError
from aw2_lab.sprite_extraction import terrain_sample
from aw2_lab.sprite_pack import (
    TERRAIN_CLASSES,
    build_sprite_pack,
    terrain_frame,
    terrain_variant_frame,
)
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
    source = rom.read_bytes()
    expected_variants = {
        f"{value & 31}:{tile}"
        for tile, value in enumerate(source[0x0C1BC4:0x0C1FC4])
        if value & 31 in (4, 5, 7, 13)
    }
    manifest = build_sprite_pack(rom, tmp_path)
    assert set(manifest["terrain_variants"]) == expected_variants
    shoals = [int(key.split(":")[1]) for key in expected_variants if key.startswith("13:")]
    assert len(shoals) == 36
    assert len({terrain_variant_frame(source, tile)[2] for tile in shoals}) >= 4
    roads = [int(key.split(":")[1]) for key in expected_variants if key.startswith("5:")]
    assert len(roads) == 40
    assert len({terrain_variant_frame(source, tile)[2] for tile in roads}) >= 4
    woods = [int(key.split(":")[1]) for key in expected_variants if key.startswith("4:")]
    assert len(woods) == 19
    assert len({terrain_variant_frame(source, tile)[2] for tile in woods}) == 19
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
    with pytest.raises(ValueError, match="verified woods, road, sea, or shoal"):
        terrain_variant_frame(b"", tile)
