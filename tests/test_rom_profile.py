import pytest

from aw2_lab import rom_profile
from aw2_lab.rom_profile import AW2_US_REVISION_0, UnsupportedRomError, sha256_file


def test_supported_us_rom_profile_records_verified_identity() -> None:
    profile = AW2_US_REVISION_0

    assert profile.title == "ADVANCEWARS2"
    assert profile.game_code == "AW2E"
    assert profile.maker_code == "01"
    assert profile.revision == 0
    assert profile.sha256 == "ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134"
    assert profile.memory_layout_version == "aw2-us-v1"
    assert profile.decoder_version == "1"


def test_sha256_file_hashes_file_contents(tmp_path) -> None:
    rom = tmp_path / "rom.gba"
    rom.write_bytes(b"synthetic ROM bytes")

    assert sha256_file(rom) == "b713e1424b4b08d9553954e2bc1b1003e8abb7df6b6f7ab0d8b0a3abbb1037c2"


def test_select_rom_profile_returns_checksum_verified_profile(monkeypatch, tmp_path) -> None:
    rom = tmp_path / "supported.gba"
    rom.touch()
    monkeypatch.setattr(rom_profile, "sha256_file", lambda _: AW2_US_REVISION_0.sha256)

    assert rom_profile.select_rom_profile(rom) is AW2_US_REVISION_0


def test_select_rom_profile_rejects_unknown_image_with_header_diagnostic(tmp_path) -> None:
    rom = tmp_path / "modified.gba"
    data = bytearray(0xBD)
    data[0xA0:0xAC] = b"ADVANCEWARS2"
    data[0xAC:0xB0] = b"AW2E"
    data[0xB0:0xB2] = b"01"
    data[0xBC] = 1
    rom.write_bytes(data)

    with pytest.raises(UnsupportedRomError) as error:
        rom_profile.select_rom_profile(rom)

    message = str(error.value)
    assert sha256_file(rom) in message
    assert "title='ADVANCEWARS2'" in message
    assert "game_code='AW2E'" in message
    assert "revision=1" in message
