"""Checkpoint state capture, integrity checks, and pre-restore compatibility."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol

from aw2_lab.match_contract import CheckpointManifest, CheckpointStateArtifact, MatchLifecycle
from aw2_lab.match_observation import MATCH_OBSERVATION_SCHEMA_VERSION
from aw2_lab.state_model import GAME_STATE_SCHEMA_VERSION
from aw2_lab.unit_identity import IDENTITY_SCHEMA_VERSION


class CheckpointCompatibilityError(ValueError):
    """Raised before restoration when a checkpoint does not match this runtime."""


class CheckpointArtifactError(ValueError):
    """Raised when checkpoint state bytes do not match the manifest."""


class CheckpointBridge(Protocol):
    async def save_state_buffer_with_frame(self) -> tuple[bytes, int]: ...

    async def load_state_buffer(self, state: bytes) -> int: ...


@dataclass(frozen=True, slots=True)
class CapturedCheckpointState:
    """State bytes and their manifest metadata from one bridge checkpoint call."""

    data: bytes
    artifact: CheckpointStateArtifact
    frame: int


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
            "Checkpoint is incompatible with this runtime: " + ", ".join(mismatches)
        )


def validate_checkpoint_state(manifest: CheckpointManifest, state: bytes) -> None:
    """Verify checkpoint blob size and digest before passing it to mGBA."""
    if not isinstance(state, bytes) or not state:
        raise CheckpointArtifactError("Checkpoint state must be non-empty bytes")
    artifact = manifest.state_artifact
    if len(state) != artifact.size_bytes:
        raise CheckpointArtifactError("Checkpoint state size does not match its manifest")
    if hashlib.sha256(state).hexdigest() != artifact.sha256:
        raise CheckpointArtifactError("Checkpoint state SHA-256 does not match its manifest")


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
    restored_frame = await bridge.load_state_buffer(state)
    if restored_frame != manifest.last_frame:
        raise CheckpointArtifactError(
            "Restored emulator frame does not match the checkpoint manifest"
        )
    return restored_frame
