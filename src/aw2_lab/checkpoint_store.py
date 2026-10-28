"""Local immutable checkpoints, bounded archive transfer, and atomic CURRENT commits."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from pydantic import ValidationError

from aw2_lab.checkpoint import (
    CheckpointArtifactError,
    CheckpointError,
    CheckpointStorageError,
    checkpoint_observation_metadata,
    read_checkpoint_pointer,
    validate_checkpoint_pointer,
    validate_checkpoint_state,
)
from aw2_lab.match_contract import (
    CheckpointCommitPointer,
    CheckpointManifest,
    CheckpointReference,
    CommandResult,
    ErrorCode,
)

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_STATE_BYTES = 3 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_MANIFEST_BYTES + MAX_STATE_BYTES + 64 * 1024


class CheckpointStore:
    """One trusted storage root; operation arguments are IDs and bytes, never paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = threading.RLock()

    def save(self, manifest: CheckpointManifest, state: bytes) -> CheckpointReference:
        """Publish a complete immutable checkpoint without changing CURRENT."""
        validate_checkpoint_state(manifest, state)
        checkpoint_observation_metadata(manifest)
        encoded = manifest.model_dump_json().encode("utf-8")
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise _corrupt("Checkpoint manifest exceeds the size limit")
        with self._lock:
            temporary: Path | None = None
            try:
                self._initialize()
                destination = self._directory(manifest.checkpoint_id)
                if destination.exists():
                    existing, existing_state = self.load(manifest.checkpoint_id)
                    if existing != manifest or existing_state != state:
                        raise CheckpointError(
                            ErrorCode.INVALID_REQUEST,
                            "Checkpoint ID already identifies different content",
                        )
                    return _reference(existing)
                temporary = Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=self.root))
                _write_file(temporary / "state.bin", state)
                _write_file(temporary / "manifest.json", encoded)
                _sync_directory(temporary)
                os.rename(temporary, destination)
                temporary = None
                _sync_directory(self.root)
                return _reference(manifest)
            except OSError as error:
                raise _io_error("save checkpoint", error) from error
            finally:
                if temporary is not None:
                    shutil.rmtree(temporary, ignore_errors=True)

    def load(self, checkpoint_id: UUID) -> tuple[CheckpointManifest, bytes]:
        """Validate both immutable files before returning checkpoint contents."""
        with self._lock:
            manifest, _ = self._manifest(checkpoint_id)
            state = self._read(self._directory(checkpoint_id) / "state.bin", MAX_STATE_BYTES)
            validate_checkpoint_state(manifest, state)
            return manifest, state

    def commit(
        self, checkpoint_id: UUID, *, command_result: CommandResult | None = None
    ) -> CheckpointCommitPointer:
        """Atomically select a durable checkpoint, including the exact terminal result."""
        with self._lock:
            temporary: Path | None = None
            manifest, manifest_bytes = self._manifest(checkpoint_id)
            # Never publish CURRENT for an incomplete or corrupt state blob.
            self.load(checkpoint_id)
            pointer = CheckpointCommitPointer(
                checkpoint_id=checkpoint_id,
                manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                match_id=manifest.match.match_id,
                revision=manifest.match.revision,
                command_result=command_result,
                committed_at=datetime.now(UTC),
            )
            validate_checkpoint_pointer(pointer, manifest, manifest_bytes)
            try:
                descriptor, filename = tempfile.mkstemp(prefix=".current-", dir=self.root)
                temporary = Path(filename)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(pointer.model_dump_json().encode("utf-8"))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.root / "CURRENT")
                temporary = None
                _sync_directory(self.root)
            except OSError as error:
                raise _io_error("commit checkpoint", error) from error
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass  # The original commit error remains authoritative.
            return pointer

    def current(self) -> CheckpointCommitPointer | None:
        with self._lock:
            pointer_path = self.root / "CURRENT"
            if pointer_path.is_symlink():
                raise _corrupt("Checkpoint pointer must be a regular file")
            pointer = read_checkpoint_pointer(pointer_path, allow_missing=True)
            if pointer is not None:
                manifest, encoded = self._manifest(pointer.checkpoint_id)
                validate_checkpoint_pointer(pointer, manifest, encoded)
                self.load(pointer.checkpoint_id)
            return pointer

    def export_archive(self, checkpoint_id: UUID) -> bytes:
        """Return two fixed ZIP members; no server filenames enter the archive."""
        manifest, state = self.load(checkpoint_id)
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            archive.writestr("manifest.json", manifest.model_dump_json())
            archive.writestr("state.bin", state)
        return output.getvalue()

    @staticmethod
    def decode_archive(data: bytes) -> tuple[CheckpointManifest, bytes]:
        """Validate bounded, uncompressed archive bytes without extracting files."""
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ARCHIVE_BYTES:
            raise _corrupt("Checkpoint archive is empty or exceeds the size limit")
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) != 2 or {m.filename for m in members} != {
                    "manifest.json",
                    "state.bin",
                }:
                    raise _corrupt(
                        "Checkpoint archive must contain exactly manifest.json and state.bin"
                    )
                for member in members:
                    limit = (
                        MAX_MANIFEST_BYTES
                        if member.filename == "manifest.json"
                        else MAX_STATE_BYTES
                    )
                    if (
                        member.compress_type != ZIP_STORED
                        or member.flag_bits & 1
                        or not 0 < member.file_size <= limit
                        or member.compress_size != member.file_size
                    ):
                        raise _corrupt("Checkpoint archive member format or size is invalid")
                encoded = archive.read("manifest.json")
                state = archive.read("state.bin")
        except CheckpointError:
            raise
        except (BadZipFile, ValueError, NotImplementedError, EOFError, RuntimeError) as error:
            raise _corrupt("Checkpoint archive is malformed") from error
        manifest = _parse_manifest(encoded)
        checkpoint_observation_metadata(manifest)
        validate_checkpoint_state(manifest, state)
        return manifest, state

    def import_archive(self, data: bytes) -> CheckpointReference:
        """Store a validated archive without loading it or changing CURRENT."""
        manifest, state = self.decode_archive(data)
        return self.save(manifest, state)

    def _initialize(self) -> None:
        missing: list[Path] = []
        directory = self.root
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700, exist_ok=True)
            _sync_directory(directory.parent)

    def _directory(self, checkpoint_id: UUID) -> Path:
        if not isinstance(checkpoint_id, UUID):
            raise CheckpointError(ErrorCode.INVALID_REQUEST, "Checkpoint ID must be a UUID")
        directory = self.root / str(checkpoint_id)
        if directory.is_symlink():
            raise _corrupt("Checkpoint directory must not be a symbolic link")
        return directory

    def _manifest(self, checkpoint_id: UUID) -> tuple[CheckpointManifest, bytes]:
        encoded = self._read(self._directory(checkpoint_id) / "manifest.json", MAX_MANIFEST_BYTES)
        manifest = _parse_manifest(encoded)
        if manifest.checkpoint_id != checkpoint_id:
            raise _corrupt("Checkpoint ID does not match its stored manifest")
        checkpoint_observation_metadata(manifest)
        return manifest, encoded

    @staticmethod
    def _read(path: Path, limit: int) -> bytes:
        try:
            if path.is_symlink():
                raise _corrupt("Checkpoint artifacts must be regular files")
            with path.open("rb") as source:
                data = source.read(limit + 1)
        except FileNotFoundError as error:
            raise _corrupt("A checkpoint artifact is missing") from error
        except OSError as error:
            raise _io_error("read checkpoint", error) from error
        if not 0 < len(data) <= limit:
            raise _corrupt("Checkpoint artifact is empty or exceeds the size limit")
        return data


def _parse_manifest(encoded: bytes) -> CheckpointManifest:
    try:
        return CheckpointManifest.model_validate_json(encoded)
    except ValidationError as error:
        raise _corrupt("Checkpoint manifest is malformed or unsupported") from error


def _reference(manifest: CheckpointManifest) -> CheckpointReference:
    return CheckpointReference(
        checkpoint_id=manifest.checkpoint_id,
        match_id=manifest.match.match_id,
        revision=manifest.match.revision,
        created_at=manifest.created_at,
    )


def _write_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _corrupt(message: str) -> CheckpointArtifactError:
    return CheckpointArtifactError(ErrorCode.CHECKPOINT_CORRUPT, message)


def _io_error(operation: str, error: OSError) -> CheckpointStorageError:
    return CheckpointStorageError(
        ErrorCode.STORAGE_UNAVAILABLE,
        "Checkpoint storage operation failed",
        details={"operation": operation, "cause": type(error).__name__, "errno": error.errno},
    )
