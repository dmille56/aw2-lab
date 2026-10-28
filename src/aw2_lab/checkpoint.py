"""Checkpoint state capture, integrity checks, and pre-restore compatibility."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from aw2_lab.bridge import BridgeError
from aw2_lab.match_contract import (
    CheckpointCommitPointer,
    CheckpointManifest,
    CheckpointStateArtifact,
    ErrorBody,
    ErrorCode,
    MatchLifecycle,
)
from aw2_lab.match_observation import MATCH_OBSERVATION_SCHEMA_VERSION, MatchObservationMetadata
from aw2_lab.state_model import GAME_STATE_SCHEMA_VERSION
from aw2_lab.unit_identity import IDENTITY_SCHEMA_VERSION


class CheckpointError(RuntimeError):
    """Checkpoint failure with a stable, safe diagnostic for clients and logs."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, str | int | bool | None] | None = None,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            details=details or {},
        )


class CheckpointCompatibilityError(CheckpointError):
    """Raised before restoration when a checkpoint does not match this runtime."""


class CheckpointArtifactError(CheckpointError):
    """Raised when checkpoint files or state bytes are missing or corrupt."""


class CheckpointStorageError(CheckpointError):
    """Raised when trusted checkpoint storage cannot be read."""


class CheckpointRestoreError(CheckpointError):
    """Raised when the emulator cannot restore an otherwise validated artifact."""


class CheckpointBridge(Protocol):
    async def save_state_buffer_with_frame(self) -> tuple[bytes, int]: ...

    async def load_state_buffer(self, state: bytes) -> int: ...


@dataclass(frozen=True, slots=True)
class CapturedCheckpointState:
    """State bytes and their manifest metadata from one bridge checkpoint call."""

    data: bytes
    artifact: CheckpointStateArtifact
    frame: int


def checkpoint_observation_metadata(manifest: CheckpointManifest) -> MatchObservationMetadata:
    """Convert the persisted public ledger to the observer's validated metadata."""
    try:
        return MatchObservationMetadata.from_dict(
            {
                "schema_version": manifest.observation_schema_version,
                "match_id": str(manifest.match.match_id),
                "revision": manifest.match.revision,
                "last_frame": manifest.last_frame,
                "identity_metadata": manifest.identity_metadata.model_dump(
                    mode="json", exclude={"contract_version"}
                ),
            }
        )
    except (TypeError, ValueError) as error:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint identity metadata is invalid or unsupported",
        ) from error


def read_checkpoint_manifest(path: Path) -> CheckpointManifest:
    """Read and validate a bounded manifest without exposing the local path."""
    try:
        size = path.stat().st_size
        if size > 1024 * 1024:
            raise CheckpointArtifactError(
                ErrorCode.CHECKPOINT_CORRUPT,
                "Checkpoint manifest exceeds the size limit",
                details={"artifact": "manifest", "size_bytes": size},
            )
        data = path.read_bytes()
    except FileNotFoundError as error:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint manifest is missing",
            details={"artifact": "manifest"},
        ) from error
    except OSError as error:
        raise _storage_error("read manifest", error) from error
    try:
        return CheckpointManifest.model_validate_json(data)
    except ValidationError as error:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint manifest is malformed or uses an unsupported schema",
            details={"artifact": "manifest", "cause": type(error).__name__},
        ) from error


def read_checkpoint_pointer(
    path: Path, *, allow_missing: bool = False
) -> CheckpointCommitPointer | None:
    """Read CURRENT, distinguishing an empty store from a missing requested pointer."""
    try:
        size = path.stat().st_size
        if size > 64 * 1024:
            raise CheckpointArtifactError(
                ErrorCode.CHECKPOINT_CORRUPT,
                "Checkpoint pointer exceeds the size limit",
                details={"artifact": "current_pointer", "size_bytes": size},
            )
        data = path.read_bytes()
    except FileNotFoundError as error:
        if allow_missing:
            return None
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "The committed checkpoint pointer is missing",
            details={"artifact": "current_pointer"},
        ) from error
    except OSError as error:
        raise _storage_error("read current pointer", error) from error
    try:
        return CheckpointCommitPointer.model_validate_json(data)
    except ValidationError as error:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "The committed checkpoint pointer is malformed",
            details={"artifact": "current_pointer", "cause": type(error).__name__},
        ) from error


def read_checkpoint_state(path: Path, manifest: CheckpointManifest) -> bytes:
    """Read a bounded state blob and verify its manifest digest before restore."""
    try:
        size = path.stat().st_size
        if size != manifest.state_artifact.size_bytes:
            raise CheckpointArtifactError(
                ErrorCode.CHECKPOINT_CORRUPT,
                "Checkpoint state size does not match its manifest",
                details={"artifact": "state", "expected_bytes": manifest.state_artifact.size_bytes},
            )
        state = path.read_bytes()
    except FileNotFoundError as error:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint state artifact is missing",
            details={"artifact": "state"},
        ) from error
    except OSError as error:
        raise _storage_error("read state", error) from error
    validate_checkpoint_state(manifest, state)
    return state


def validate_checkpoint_pointer(
    pointer: CheckpointCommitPointer,
    manifest: CheckpointManifest,
    manifest_bytes: bytes,
) -> None:
    """Check that CURRENT and its manifest refer to the same committed state."""
    mismatches: list[str] = []
    if hashlib.sha256(manifest_bytes).hexdigest() != pointer.manifest_sha256:
        mismatches.append("manifest digest")
    if pointer.checkpoint_id != manifest.checkpoint_id:
        mismatches.append("checkpoint ID")
    if pointer.match_id != manifest.match.match_id:
        mismatches.append("match ID")
    if pointer.revision != manifest.match.revision:
        mismatches.append("revision")
    result = pointer.command_result
    if result is None:
        if manifest.originating_command_id is not None:
            mismatches.append("originating command ID")
    elif result.command_id != manifest.originating_command_id:
        mismatches.append("command ID")
    if mismatches:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint pointer and manifest disagree",
            details={"fields": ", ".join(mismatches)},
        )


async def capture_checkpoint_state(bridge: CheckpointBridge) -> CapturedCheckpointState:
    """Capture a full mGBA state, including save RAM, through the bridge."""
    state, frame = await bridge.save_state_buffer_with_frame()
    artifact = CheckpointStateArtifact(
        sha256=hashlib.sha256(state).hexdigest(),
        size_bytes=len(state),
        includes_save_ram=True,
    )
    return CapturedCheckpointState(state, artifact, frame)


def validate_checkpoint_compatibility(
    manifest: CheckpointManifest,
    *,
    rom_sha256: str,
    emulator_build: str,
    emulator_mode: Literal["headless", "windowed"],
) -> None:
    """Reject incompatible checkpoint metadata before touching emulator state."""
    mismatches: list[str] = []
    if manifest.manifest_schema_version != 1:
        mismatches.append("manifest schema")
    if manifest.rom_sha256 != rom_sha256:
        mismatches.append("ROM checksum")
    if manifest.emulator_build != emulator_build:
        mismatches.append("emulator build")
    if manifest.emulator_mode != emulator_mode:
        mismatches.append("emulator mode")
    if manifest.decoder_schema_version != GAME_STATE_SCHEMA_VERSION:
        mismatches.append("decoder schema")
    if manifest.observation_schema_version != MATCH_OBSERVATION_SCHEMA_VERSION:
        mismatches.append("match observation schema")
    if manifest.identity_metadata.schema_version != IDENTITY_SCHEMA_VERSION:
        mismatches.append("unit identity schema")
    if manifest.match.lifecycle is MatchLifecycle.EXECUTING:
        mismatches.append("match is not at a command boundary")
    if not manifest.state_artifact.includes_save_ram:
        mismatches.append("state does not include save RAM")
    if mismatches:
        raise CheckpointCompatibilityError(
            ErrorCode.CHECKPOINT_INCOMPATIBLE,
            "Checkpoint is incompatible with this runtime",
            details={"fields": ", ".join(mismatches)},
        )


def validate_checkpoint_state(manifest: CheckpointManifest, state: bytes) -> None:
    """Verify checkpoint blob size and digest before passing it to mGBA."""
    if not isinstance(state, bytes) or not state:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint state must be non-empty bytes",
            details={"artifact": "state"},
        )
    artifact = manifest.state_artifact
    if len(state) != artifact.size_bytes:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint state size does not match its manifest",
            details={"artifact": "state", "expected_bytes": artifact.size_bytes},
        )
    if hashlib.sha256(state).hexdigest() != artifact.sha256:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Checkpoint state SHA-256 does not match its manifest",
            details={"artifact": "state", "cause": "sha256_mismatch"},
        )


async def restore_checkpoint_state(
    bridge: CheckpointBridge,
    manifest: CheckpointManifest,
    state: bytes,
    *,
    rom_sha256: str,
    emulator_build: str,
    emulator_mode: Literal["headless", "windowed"],
) -> int:
    """Validate metadata and bytes, then restore the full state through mGBA."""
    validate_checkpoint_compatibility(
        manifest,
        rom_sha256=rom_sha256,
        emulator_build=emulator_build,
        emulator_mode=emulator_mode,
    )
    validate_checkpoint_state(manifest, state)
    try:
        restored_frame = await bridge.load_state_buffer(state)
    except BridgeError as error:
        raise CheckpointRestoreError(
            ErrorCode.RECOVERY_REQUIRED,
            "The emulator could not restore the validated checkpoint",
            details={"cause": type(error).__name__},
        ) from error
    if restored_frame != manifest.last_frame:
        raise CheckpointArtifactError(
            ErrorCode.CHECKPOINT_CORRUPT,
            "Restored emulator frame does not match the checkpoint manifest",
            details={"expected_frame": manifest.last_frame, "restored_frame": restored_frame},
        )
    return restored_frame


def _storage_error(operation: str, error: OSError) -> CheckpointStorageError:
    details: dict[str, str | int | bool | None] = {
        "operation": operation,
        "cause": type(error).__name__,
    }
    if error.errno is not None:
        details["errno"] = error.errno
    return CheckpointStorageError(
        ErrorCode.STORAGE_UNAVAILABLE,
        "Checkpoint storage is unavailable",
        retryable=True,
        details=details,
    )
