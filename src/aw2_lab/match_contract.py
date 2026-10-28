"""Versioned public models for the initial, fixed Milestone 3 match contract."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

CONTRACT_VERSION = 1
MAX_SAFE_REVISION = (1 << 53) - 1
Revision = Annotated[int, Field(ge=0, le=MAX_SAFE_REVISION)]
CoordinateValue = Annotated[int, Field(ge=0)]


class ContractModel(BaseModel):
    """Base for public documents; additive-compatible fields require a version bump policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal[1] = 1


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


class MatchRules(ContractModel):
    day_limit: Annotated[int, Field(ge=1, le=99)] = 30
    starting_funds: Annotated[int, Field(ge=0)] = 1000
    fog: Literal[False] = False
    co_powers: Literal[True] = True
    starting_weather: Literal["clear"] = "clear"


class FixedMatchConfiguration(ContractModel):
    """The only configuration advertised as playable by contract version 1."""

    map_id: Literal["bean_island"] = "bean_island"
    player_1_co: Literal["andy"] = "andy"
    player_2_co: Literal["max"] = "max"
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
        "move_attack",
        "move_capture",
        "purchase",
        "end_turn",
        "surrender",
    )
    supported_features: tuple[str, ...] = (
        "single_active_match",
        "two_external_players",
        "fixed_versus_configuration",
        "structured_observation",
        "screenshots",
        "command_status_polling",
        "checkpoints",
    )
    unsupported_features: tuple[str, ...] = (
        "multiple_active_matches",
        "configurable_maps_cos_rules_weather_or_teams",
        "fog_of_war",
        "co_power_activation",
        "transport_loading_or_unloading",
        "resupply",
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
    path: tuple[Coordinate, ...]


class MoveAttackAction(ContractModel):
    kind: Literal["move_attack"] = "move_attack"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...]
    target: Coordinate


class MoveCaptureAction(ContractModel):
    kind: Literal["move_capture"] = "move_capture"
    unit_id: str = Field(min_length=1)
    path: tuple[Coordinate, ...]


class PurchaseAction(ContractModel):
    kind: Literal["purchase"] = "purchase"
    property: Coordinate
    unit_type: str = Field(min_length=1)


class EndTurnAction(ContractModel):
    kind: Literal["end_turn"] = "end_turn"


class SurrenderAction(ContractModel):
    kind: Literal["surrender"] = "surrender"


GameplayAction = Annotated[
    MoveWaitAction
    | MoveAttackAction
    | MoveCaptureAction
    | PurchaseAction
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
    manifest_schema_version: Literal[1] = 1
    match: MatchSummary
    originating_command_id: UUID | None = None
    rom_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    emulator_build: str = Field(min_length=1)
    emulator_mode: Literal["headless", "windowed"]
    state_artifact: CheckpointStateArtifact
    decoder_schema_version: Annotated[int, Field(ge=1)]
    observation_schema_version: Annotated[int, Field(ge=1)]
    identity_metadata: CheckpointIdentityMetadata
    last_frame: Annotated[int, Field(ge=0, le=(1 << 32) - 1)]
    created_at: datetime


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
    JOURNAL_CORRUPT = "journal_corrupt"
    STORAGE_UNAVAILABLE = "storage_unavailable"
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
