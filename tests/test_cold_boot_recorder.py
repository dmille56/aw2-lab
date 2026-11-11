from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aw2_lab import cold_boot_recorder
from aw2_lab.cold_boot_recorder import _decode_sharkport_save, _record_save_copy_result


@pytest.mark.parametrize("location", ["package", "repository", "explicit"])
def test_recorder_resolves_bridge_for_installed_and_repository_runs(
    monkeypatch, tmp_path, location
) -> None:
    module_path = tmp_path / "site-packages" / "aw2_lab" / "cold_boot_recorder.py"
    packaged_bridge = module_path.parent / "lua" / "bridge.lua"
    repository_bridge = tmp_path / "lua" / "bridge.lua"
    explicit_bridge = tmp_path / "custom.lua"
    expected = {
        "package": packaged_bridge,
        "repository": repository_bridge,
        "explicit": explicit_bridge,
    }[location]
    # Keep the fallback present to check that the packaged bridge takes priority.
    repository_bridge.parent.mkdir(parents=True)
    repository_bridge.touch()
    if location != "repository":
        packaged_bridge.parent.mkdir(parents=True)
        packaged_bridge.touch()
    expected.touch()
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(b"test ROM")
    monkeypatch.setattr(cold_boot_recorder, "__file__", str(module_path))
    monkeypatch.setattr(cold_boot_recorder, "select_rom_profile", lambda _: None)

    def create_output(directory):
        directory.mkdir()
        return directory

    monkeypatch.setattr(cold_boot_recorder, "_create_output_directory", create_output)

    def capture_settings(settings):
        assert Path(settings.bridge_script) == expected
        raise RuntimeError("bridge resolved")

    monkeypatch.setattr(cold_boot_recorder, "EmulatorLauncher", capture_settings)
    arguments = [
        "--rom",
        str(rom),
        "--mode",
        "headless",
        "--save-mode",
        "fresh",
        "--output",
        str(tmp_path / "output"),
    ]
    if location == "explicit":
        arguments.extend(["--lua-bridge", str(explicit_bridge)])
    with pytest.raises(RuntimeError, match="bridge resolved"):
        cold_boot_recorder.recorder_main(arguments)


def _sharkport_save(rom_identity: bytes, payload: bytes) -> bytes:
    def field(value: bytes) -> bytes:
        return len(value).to_bytes(4, "little") + value

    header = rom_identity + bytes(0x1C - len(rom_identity))
    record = header + payload
    return b"".join(
        (
            len(b"SharkPortSave").to_bytes(4, "little"),
            b"SharkPortSave",
            (0x000F0000).to_bytes(4, "little"),
            field(b"Advance Wars 2"),
            field(b"2002-01-01"),
            field(b"all unlocks"),
            len(record).to_bytes(4, "little"),
            record,
            bytes(4),
        )
    )


def test_decode_sharkport_save_extracts_sram_for_matching_rom(tmp_path) -> None:
    rom_identity = b"ADVANCEWARS2AW2E"
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(bytes(0xA0) + rom_identity + bytes(0x100))
    payload = bytes(index % 251 for index in range(0x10000))
    source = tmp_path / "all-unlocked.sps"
    source.write_bytes(_sharkport_save(rom_identity, payload))

    assert _decode_sharkport_save(source, rom) == payload


def test_decode_sharkport_save_rejects_a_different_rom(tmp_path) -> None:
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(bytes(0xA0) + b"ADVANCEWARS2AW2E" + bytes(0x100))
    source = tmp_path / "other-game.sps"
    source.write_bytes(_sharkport_save(b"OTHER-GAME-ROM!!", bytes(0x10000)))

    try:
        _decode_sharkport_save(source, rom)
    except ValueError as error:
        assert "different ROM" in str(error)
    else:
        raise AssertionError("expected ROM identity mismatch to be rejected")


def test_decode_sharkport_save_rejects_truncated_container(tmp_path) -> None:
    rom_identity = b"ADVANCEWARS2AW2E"
    rom = tmp_path / "aw2.gba"
    rom.write_bytes(bytes(0xA0) + rom_identity + bytes(0x100))
    source = tmp_path / "truncated.sps"
    source.write_bytes(_sharkport_save(rom_identity, bytes(0x10000))[:-5])

    try:
        _decode_sharkport_save(source, rom)
    except ValueError as error:
        assert "truncated payload" in str(error)
    else:
        raise AssertionError("expected truncated save to be rejected")


def test_save_copy_result_records_reusable_pair_and_preserves_source(tmp_path) -> None:
    output = tmp_path / "evidence"
    save_directory = output / "save-data"
    save_directory.mkdir(parents=True)
    source_save = tmp_path / "source.sav"
    source_save.write_bytes(b"source save")
    original_hash = hashlib.sha256(source_save.read_bytes()).hexdigest()
    prepared_rom = save_directory / "aw2.gba"
    prepared_rom.write_bytes(b"prepared ROM")
    isolated_save = save_directory / "aw2.sav"
    isolated_save.write_bytes(b"isolated save after user progress")
    manifest = {"existing_save_sha256": original_hash}

    source_unchanged = _record_save_copy_result(
        output, manifest, prepared_rom, isolated_save, source_save
    )

    assert source_unchanged
    assert hashlib.sha256(source_save.read_bytes()).hexdigest() == original_hash
    assert manifest["prepared_rom"] == "save-data/aw2.gba"
    assert manifest["isolated_save"] == {
        "path": "save-data/aw2.sav",
        "sha256": hashlib.sha256(isolated_save.read_bytes()).hexdigest(),
        "source_save_unchanged": True,
    }
    assert json.loads((output / "manifest.json").read_text()) == manifest


def test_save_copy_result_reports_missing_fresh_save(tmp_path) -> None:
    output = tmp_path / "evidence"
    save_directory = output / "save-data"
    save_directory.mkdir(parents=True)
    prepared_rom = save_directory / "aw2.gba"
    prepared_rom.write_bytes(b"prepared ROM")
    manifest = {"existing_save_sha256": None}

    assert _record_save_copy_result(
        output, manifest, prepared_rom, save_directory / "aw2.sav", None
    )
    assert manifest["isolated_save"] == {
        "path": None,
        "sha256": None,
        "source_save_unchanged": True,
    }
