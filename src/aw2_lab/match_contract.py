"""Versioned public models for the Milestone 3 contract and Milestone 5 extensions."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from aw2_lab.map_catalog import MapId

CONTRACT_VERSION = 1
MAX_SAFE_REVISION = (1 << 53) - 1
Revision = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_REVISION)]
CoordinateValue = Annotated[int, Field(strict=True, ge=0)]


class ContractModel(BaseModel):
    """Base for public documents; additive-compatible fields require a version bump policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    contract_version: Literal[1] = 1

    @field_validator("contract_version", mode="before")
    @classmethod
    def validate_contract_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Contract version must be an integer")
        return value


class MatchLifecycle(StrEnum):
    SETUP = "setup"
    PLAYABLE = "playable"
    EXECUTING = "executing"
    FINISHED = "finished"
    RECOVERY_REQUIRED = "recovery_required"
    CLOSED = "closed"


class PlayerSlot(StrEnum):
    SLOT_1 = "slot_1"
    SLOT_2 = "slot_2"


class SlotStatus(StrEnum):
    OPEN = "open"
    JOINED = "joined"
    REVOKED = "revoked"


CoId = Literal[
    "nell",
    "andy",
    "max",
    "sami",
    "hachi",
    "olaf",
    "grit",
    "colin",
    "kanbei",
    "sonja",
    "sensei",
    "eagle",
    "drake",
    "jess",
    "flak",
    "lash",
    "adder",
    "hawke",
    "sturm",
]

CO_ID_VALUES: tuple[CoId, ...] = (
    "nell",
    "andy",
    "max",
    "sami",
    "hachi",
    "olaf",
    "grit",
    "colin",
    "kanbei",
    "sonja",
    "sensei",
    "eagle",
    "drake",
    "jess",
    "flak",
    "lash",
    "adder",
    "hawke",
    "sturm",
)


class MatchRules(ContractModel):
    # Rules accepted by the public setup flow; fog and starting weather remain fixed.
    day_limit: Annotated[int, Field(ge=1, le=99)] | None = 30
    starting_funds: Annotated[int, Field(ge=1000, le=5000, multiple_of=500)] = 1000
    capture_limit: Annotated[int, Field(ge=12, le=27)] | None = None
    fog: Literal[False] = False
    co_powers: bool = True
    # Durable controller/checkpoint spelling; the public API adapter exposes `weather`.
    starting_weather: Literal["clear"] = "clear"


class FixedMatchConfiguration(ContractModel):
    """Two-player configuration with selectable maps, COs, and supported rules."""

    map_id: MapId = "bean_island"
    player_1_co: CoId = "andy"
    player_2_co: CoId = "max"
    player_1_color: Literal["red"] = "red"
    player_2_color: Literal["blue"] = "blue"
    player_1_team: Literal["a"] = "a"
    player_2_team: Literal["b"] = "b"
    control: Literal["external_both"] = "external_both"
    rules: MatchRules = MatchRules()


class PlayerSlotState(ContractModel):
    slot: PlayerSlot
    status: SlotStatus
    display_name: str | None = None


class MatchSummary(ContractModel):
    match_id: UUID
    revision: Revision
    lifecycle: MatchLifecycle
    configuration: FixedMatchConfiguration
    slots: tuple[PlayerSlotState, PlayerSlotState]
    created_at: datetime

    @model_validator(mode="after")
    def validate_slot_order(self) -> MatchSummary:
        if tuple(slot.slot for slot in self.slots) != (PlayerSlot.SLOT_1, PlayerSlot.SLOT_2):
            raise ValueError("A fixed match summary must list slot 1 followed by slot 2")
        return self


class Capabilities(ContractModel):
    supported_actions: tuple[str, ...] = (
        "move_wait",
        "attack",
        "move_attack",
        "move_capture",
        "join",
        "supply",
        "dive",
        "rise",
        "silo_launch",
        "load",
        "unload",
        "purchase",
        "activate_normal_power",
        "activate_super_power",
        "end_turn",
        "surrender",
    )
    supported_features: tuple[str, ...] = (
        "single_active_match",
        "two_external_players",
        "fixed_versus_configuration",
        "map_selection",
        "structured_observation",
        "screenshots",
        "command_status_polling",
        "checkpoints",
        "transport_loading_and_unloading",
        "unit_joining",
        "apc_resupply",
        "diving_and_surfacing",
        "missile_silo_use",
    )
    unsupported_features: tuple[str, ...] = (
        "multiple_active_matches",
        "configurable_starting_weather_or_fog",
        "maps_outside_two_player_versus_catalog",
        "campaign_or_multiplayer_modes_other_than_versus",
        "competitive_player_visibility_isolation",
        "arbitrary_memory_writes_as_gameplay",
    )


class Coordinate(ContractModel):
    x: CoordinateValue
    y: CoordinateValue


class MoveWaitAction(ContractModel):
    kind: Literal["move_wait"] = "move_wait"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)


class MoveAttackAction(ContractModel):
    kind: Literal["move_attack"] = "move_attack"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)
    target: Coordinate


class AttackAction(ContractModel):
    """Attack a target from the unit's current position."""

    kind: Literal["attack"] = "attack"
    unit_id: str = Field(min_length=1)
    target: Coordinate


class MoveCaptureAction(ContractModel):
    kind: Literal["move_capture"] = "move_capture"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)


class JoinAction(ContractModel):
    """Move a unit onto an adjacent allied unit of the same type and merge."""

    kind: Literal["join"] = "join"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(min_length=1, max_length=4096)


class SupplyAction(ContractModel):
    """Move an APC and supply every adjacent allied unit."""

    kind: Literal["supply"] = "supply"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)


class DiveAction(ContractModel):
    """Move a surfaced Sub and Dive."""

    kind: Literal["dive"] = "dive"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)


class RiseAction(ContractModel):
    """Move a submerged Sub and Rise."""

    kind: Literal["rise"] = "rise"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)


class SiloLaunchAction(ContractModel):
    """Move an Infantry/Mech onto an unused silo and launch at a map coordinate."""

    kind: Literal["silo_launch"] = "silo_launch"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)
    target: Coordinate


class LoadAction(ContractModel):
    """Move one unit onto an allied transport's tile and load it."""

    kind: Literal["load"] = "load"
    unit_id: str = Field(min_length=1)
    transport_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)


class CargoDrop(ContractModel):
    unit_id: str = Field(min_length=1)
    destination: Coordinate


class UnloadAction(ContractModel):
    """Move a carrier, then unload one or more named cargo units."""

    kind: Literal["unload"] = "unload"
    transport_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...] = Field(max_length=4096)
    drops: tuple[CargoDrop, ...] = Field(min_length=1, max_length=2)


class PurchaseAction(ContractModel):
    kind: Literal["purchase"] = "purchase"
    property: Coordinate
    unit_type: str = Field(min_length=1)


class EndTurnAction(ContractModel):
    kind: Literal["end_turn"] = "end_turn"


class ActivateNormalPowerAction(ContractModel):
    kind: Literal["activate_normal_power"] = "activate_normal_power"


class ActivateSuperPowerAction(ContractModel):
    kind: Literal["activate_super_power"] = "activate_super_power"


class SurrenderAction(ContractModel):
    kind: Literal["surrender"] = "surrender"


GameplayAction = Annotated[
    MoveWaitAction
    | MoveAttackAction
    | AttackAction
    | MoveCaptureAction
    | JoinAction
    | SupplyAction
    | DiveAction
    | RiseAction
    | SiloLaunchAction
    | LoadAction
    | UnloadAction
    | PurchaseAction
    | ActivateNormalPowerAction
    | ActivateSuperPowerAction
    | EndTurnAction
    | SurrenderAction,
    Field(discriminator="kind"),
]


class CommandRequest(ContractModel):
    match_id: UUID
    player_slot: PlayerSlot
    credential: Annotated[SecretStr, Field(min_length=32, max_length=128)]
    request_id: UUID
    expected_revision: Revision
    action: GameplayAction


class CommandStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"


class CommandReceipt(ContractModel):
    command_id: UUID
    request_id: UUID
    match_id: UUID
    status: CommandStatus
    accepted_revision: Revision


class CommandResult(ContractModel):
    command_id: UUID
    request_id: UUID
    match_id: UUID
    status: CommandStatus
    accepted_revision: Revision
    resulting_revision: Revision | None = None
    error: ErrorBody | None = None
    checkpoint_id: UUID | None = None


class CheckpointStateArtifact(ContractModel):
    """Integrity and compatibility metadata for an opaque mGBA state blob."""

    format: Literal["mgba-savestate"] = "mgba-savestate"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: Annotated[int, Field(ge=1, le=3 * 1024 * 1024)]
    includes_save_ram: Literal[True] = True


class CheckpointIdentitySlot(ContractModel):
    reference: Annotated[int, Field(ge=1, le=255)]
    unit_type: Annotated[int, Field(ge=1, le=255)]
    identity_id: Annotated[int, Field(ge=1)]
    generation: Annotated[int, Field(ge=1)]
    active: bool

    @model_validator(mode="after")
    def validate_reference(self) -> CheckpointIdentitySlot:
        slot = (self.reference - 1) % 64 + 1
        if slot > 50:
            raise ValueError("Unit identity reference is outside a usable army slot")
        return self


class CheckpointIdentityMetadata(ContractModel):
    """Typed unit lifetime ledger serialized beside the emulator state blob."""

    schema_version: Annotated[int, Field(ge=1)]
    next_identity_id: Annotated[int, Field(ge=1)]
    slots: tuple[CheckpointIdentitySlot, ...]

    @model_validator(mode="after")
    def validate_unique_allocations(self) -> CheckpointIdentityMetadata:
        references = [slot.reference for slot in self.slots]
        identities = [slot.identity_id for slot in self.slots]
        if len(references) != len(set(references)):
            raise ValueError("Unit identity references must be unique")
        if len(identities) != len(set(identities)):
            raise ValueError("Unit identity IDs must be unique")
        if identities and self.next_identity_id <= max(identities):
            raise ValueError("Next identity ID must exceed every allocated identity")
        return self


class CheckpointManifest(ContractModel):
    checkpoint_id: UUID
    manifest_schema_version: Literal[1, 2] = 2
    match: MatchSummary
    originating_command_id: UUID | None = None
    slot_credential_hashes: dict[PlayerSlot, str] = Field(default_factory=dict)
    rom_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    emulator_build: str = Field(min_length=1)
    emulator_mode: Literal["headless", "windowed"]
    state_artifact: CheckpointStateArtifact
    decoder_schema_version: Annotated[int, Field(ge=1)]
    observation_schema_version: Annotated[int, Field(ge=1)]
    identity_metadata: CheckpointIdentityMetadata
    last_frame: Annotated[int, Field(ge=0, le=(1 << 32) - 1)]
    created_at: datetime

    @model_validator(mode="after")
    def validate_slot_credential_hashes(self) -> CheckpointManifest:
        if any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in self.slot_credential_hashes.values()
        ):
            raise ValueError("Slot credential hashes must be SHA-256 digests")
        return self


class CheckpointReference(ContractModel):
    checkpoint_id: UUID
    match_id: UUID
    revision: Revision
    created_at: datetime


class CheckpointCommitPointer(ContractModel):
    """Atomic current-checkpoint reference and optional committed command result."""

    pointer_schema_version: Literal[1] = 1
    checkpoint_id: UUID
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    match_id: UUID
    revision: Revision
    command_result: CommandResult | None = None
    committed_at: datetime

    @model_validator(mode="after")
    def validate_command_result(self) -> CheckpointCommitPointer:
        if self.command_result is None:
            return self
        if self.command_result.match_id != self.match_id:
            raise ValueError("Checkpoint command result belongs to another match")
        if self.command_result.checkpoint_id != self.checkpoint_id:
            raise ValueError("Checkpoint command result must reference the committed checkpoint")
        if self.command_result.status in {CommandStatus.QUEUED, CommandStatus.RUNNING}:
            raise ValueError("Checkpoint commit pointer requires a terminal command result")
        if (
            self.command_result.resulting_revision is not None
            and self.command_result.resulting_revision != self.revision
        ):
            raise ValueError("Checkpoint command result revision must match the pointer")
        return self


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    MATCH_NOT_FOUND = "match_not_found"
    ACTIVE_MATCH_EXISTS = "active_match_exists"
    MATCH_CLOSED = "match_closed"
    MATCH_FINISHED = "match_finished"
    SLOT_UNAVAILABLE = "slot_unavailable"
    INVALID_CREDENTIAL = "invalid_credential"
    PERMISSION_DENIED = "permission_denied"
    INVALID_INVITATION = "invalid_invitation"
    NOT_YOUR_TURN = "not_your_turn"
    STALE_REVISION = "stale_revision"
    REQUEST_ID_CONFLICT = "request_id_conflict"
    COMMAND_NOT_FOUND = "command_not_found"
    COMMAND_CAPACITY = "command_capacity"
    SERVER_SHUTTING_DOWN = "server_shutting_down"
    OBSERVATION_UNAVAILABLE = "observation_unavailable"
    ACTION_REJECTED = "action_rejected"
    TIMEOUT = "timeout"
    ROLLBACK_FAILED = "rollback_failed"
    RECOVERY_REQUIRED = "recovery_required"
    CHECKPOINT_INCOMPATIBLE = "checkpoint_incompatible"
    CHECKPOINT_CORRUPT = "checkpoint_corrupt"
    CHECKPOINT_NOT_FOUND = "checkpoint_not_found"
    JOURNAL_CORRUPT = "journal_corrupt"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    INTERNAL_ERROR = "internal_error"


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)


class ErrorResponse(ContractModel):
    error: ErrorBody
    request_id: UUID | None = None


class JoinSlotResponse(ContractModel):
    match: MatchSummary
    player_slot: PlayerSlot
    credential: str = Field(min_length=32, repr=False)
