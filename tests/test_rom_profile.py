from aw2_lab.rom_profile import AW2_US_REVISION_0, sha256_file


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
