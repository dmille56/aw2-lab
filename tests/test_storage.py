from pathlib import Path

import pytest

from aw2_lab.api.app import create_app
from aw2_lab.command_journal import JsonlCommandJournal
from aw2_lab.emulator import EmulatorSettings
from aw2_lab.storage import default_storage_root, resolve_storage_root


def test_default_storage_root_uses_xdg_data_home() -> None:
    assert default_storage_root({"XDG_DATA_HOME": "/tmp/aw2-data"}) == Path("/tmp/aw2-data/aw2-lab")


def test_storage_root_rejects_checkout_and_nix_store() -> None:
    checkout = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="source checkout"):
        resolve_storage_root(checkout / "runtime-data")
    with pytest.raises(ValueError, match="Nix store"):
        resolve_storage_root("/nix/store/aw2-data")


def test_app_wires_checkpoint_store_and_durable_journal(tmp_path: Path, monkeypatch) -> None:
    from aw2_lab.api import app as api_app
    from aw2_lab.rom_profile import AW2_US_REVISION_0

    monkeypatch.setattr(api_app, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    root = tmp_path / "aw2-data"
    application = create_app(
        settings=EmulatorSettings(rom_path=tmp_path / "unused.gba"), storage_root=root
    )

    assert application.state.storage_root == root.resolve()
    assert application.state.checkpoint_store.root == (root / "checkpoints").resolve()
    assert isinstance(application.state.match_controller._journal, JsonlCommandJournal)
    assert application.state.match_controller._journal.path == root / "commands.jsonl"
