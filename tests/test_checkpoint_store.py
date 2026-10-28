"""Filesystem durability and bounded checkpoint archive behavior without a ROM."""

import hashlib
import io
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from test_state_validation import memory as memory  # noqa: PLC0414
from test_state_validation import snapshot

from aw2_lab.checkpoint import CheckpointError
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.match_contract import (
    CheckpointIdentityMetadata,
    CheckpointManifest,
    CheckpointStateArtifact,
    ErrorCode,
    FixedMatchConfiguration,
    MatchLifecycle,
    MatchSummary,
    PlayerSlot,
    PlayerSlotState,
    SlotStatus,
)
from aw2_lab.match_observation import MatchObservationTracker
from aw2_lab.rom_profile import AW2_US_REVISION_0
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import GAME_STATE_SCHEMA_VERSION


def make_checkpoint(memory, *, match_id=None):
    match_id = match_id or uuid4()
    tracker = MatchObservationTracker(match_id)
    tracker.commit_boundary(decode_snapshot(replace(snapshot(memory), frame=123)))
    data = b"state including synthetic save RAM"
    manifest = CheckpointManifest(
        checkpoint_id=uuid4(),
        match=MatchSummary(
            match_id=match_id,
            revision=tracker.revision,
            lifecycle=MatchLifecycle.PLAYABLE,
            configuration=FixedMatchConfiguration(),
            slots=tuple(
                PlayerSlotState(slot=slot, status=SlotStatus.JOINED) for slot in PlayerSlot
            ),
            created_at=datetime.now(UTC),
        ),
        rom_sha256=AW2_US_REVISION_0.sha256,
        emulator_build="synthetic-mgba-build",
        emulator_mode="headless",
        state_artifact=CheckpointStateArtifact(
            sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data)
        ),
        decoder_schema_version=GAME_STATE_SCHEMA_VERSION,
        observation_schema_version=1,
        identity_metadata=CheckpointIdentityMetadata.model_validate(
            tracker.checkpoint_metadata().identity_metadata.to_dict()
        ),
        last_frame=123,
        created_at=datetime.now(UTC),
    )
    return manifest, data


def archive_with(members, *, compression=ZIP_STORED):
    output = io.BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return output.getvalue()


def test_checkpoint_roundtrip_commit_and_import_do_not_expose_paths(memory, tmp_path):
    manifest, state = make_checkpoint(memory)
    original = CheckpointStore(tmp_path / "original")
    reference = original.save(manifest, state)
    original.commit(reference.checkpoint_id)
    assert original.current().revision == manifest.match.revision
    archive = original.export_archive(reference.checkpoint_id)
    with ZipFile(io.BytesIO(archive)) as exported:
        assert set(exported.namelist()) == {"manifest.json", "state.bin"}
    imported = CheckpointStore(tmp_path / "imported")
    assert imported.import_archive(archive) == reference
    assert imported.import_archive(archive) == reference
    assert imported.current() is None
    assert imported.load(reference.checkpoint_id) == (manifest, state)
    assert str(tmp_path) not in reference.model_dump_json()


@pytest.mark.parametrize(
    "kind", ["traversal", "duplicate", "compressed", "digest", "truncated", "oversized_member"]
)
def test_import_rejects_unsafe_or_corrupt_archives_without_writing(memory, tmp_path, kind):
    manifest, state = make_checkpoint(memory)
    members = [("manifest.json", manifest.model_dump_json()), ("state.bin", state)]
    compression = ZIP_STORED
    if kind == "traversal":
        members[1] = ("../outside", state)
    elif kind == "duplicate":
        members.append(members[0])
    elif kind == "compressed":
        compression = ZIP_DEFLATED
    elif kind == "digest":
        members[1] = ("state.bin", b"wrong content")
    elif kind == "oversized_member":
        members[1] = ("state.bin", b"x" * (3 * 1024 * 1024 + 1))
    if kind == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive = archive_with(members, compression=compression)
    else:
        archive = archive_with(members, compression=compression)
    if kind == "truncated":
        archive = archive[:-10]
    store = CheckpointStore(tmp_path / "storage")
    with pytest.raises(CheckpointError) as failure:
        store.import_archive(archive)
    assert failure.value.body.code is ErrorCode.CHECKPOINT_CORRUPT
    assert not store.root.exists()


def test_partial_checkpoint_write_does_not_replace_current(memory, tmp_path, monkeypatch):
    import aw2_lab.checkpoint_store as module

    manifest, state = make_checkpoint(memory)
    store = CheckpointStore(tmp_path / "storage")
    store.save(manifest, state)
    pointer = store.commit(manifest.checkpoint_id)
    other = manifest.model_copy(update={"checkpoint_id": uuid4()})
    write = module._write_file

    def fail_manifest(path, data):
        if path.name == "manifest.json":
            raise OSError(28, "synthetic full disk")
        write(path, data)

    monkeypatch.setattr(module, "_write_file", fail_manifest)
    with pytest.raises(CheckpointError) as failure:
        store.save(other, state)
    assert failure.value.body.code is ErrorCode.STORAGE_UNAVAILABLE
    assert str(tmp_path) not in failure.value.body.model_dump_json()
    assert store.current() == pointer
    assert not (store.root / str(other.checkpoint_id)).exists()
    assert not list(store.root.glob(".checkpoint-*"))


def test_corrupt_current_or_state_is_never_used_as_fallback(memory, tmp_path):
    manifest, state = make_checkpoint(memory)
    store = CheckpointStore(tmp_path)
    store.save(manifest, state)
    store.commit(manifest.checkpoint_id)
    (tmp_path / str(manifest.checkpoint_id) / "state.bin").write_bytes(b"partial")
    with pytest.raises(CheckpointError) as failure:
        store.current()
    assert failure.value.body.code is ErrorCode.CHECKPOINT_CORRUPT
    with pytest.raises(CheckpointError):
        store.load("../escape")
    with pytest.raises(CheckpointError):
        store.load(uuid4())


def test_checkpoint_id_collision_cannot_overwrite_existing_data(memory, tmp_path):
    manifest, state = make_checkpoint(memory)
    store = CheckpointStore(tmp_path)
    store.save(manifest, state)
    changed = manifest.model_copy(update={"emulator_build": "different"})
    with pytest.raises(CheckpointError) as failure:
        store.save(changed, state)
    assert failure.value.body.code is ErrorCode.INVALID_REQUEST
    assert store.load(manifest.checkpoint_id) == (manifest, state)


def test_failed_current_replacement_keeps_previous_committed_pointer(memory, tmp_path, monkeypatch):
    import aw2_lab.checkpoint_store as module

    manifest, state = make_checkpoint(memory)
    store = CheckpointStore(tmp_path)
    store.save(manifest, state)
    original = store.commit(manifest.checkpoint_id)
    other = manifest.model_copy(update={"checkpoint_id": uuid4()})
    store.save(other, state)

    def fail_replace(*args):
        raise OSError(5, "synthetic I/O failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(CheckpointError) as failure:
        store.commit(other.checkpoint_id)
    assert failure.value.body.code is ErrorCode.STORAGE_UNAVAILABLE
    assert store.current() == original
    assert not list(tmp_path.glob(".current-*"))


def test_export_cannot_follow_a_stored_artifact_symlink(memory, tmp_path):
    manifest, state = make_checkpoint(memory)
    store = CheckpointStore(tmp_path / "storage")
    store.save(manifest, state)
    outside = tmp_path / "private.txt"
    outside.write_text("private sentinel")
    stored = store.root / str(manifest.checkpoint_id) / "state.bin"
    stored.unlink()
    stored.symlink_to(outside)
    with pytest.raises(CheckpointError) as failure:
        store.export_archive(manifest.checkpoint_id)
    assert failure.value.body.code is ErrorCode.CHECKPOINT_CORRUPT
    assert "private sentinel" not in failure.value.body.model_dump_json()
