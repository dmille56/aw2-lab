"""Shared game-contract v1 payloads for HTTP, SDK, and future MCP adapters.

Payload validation does not authenticate callers or advertise runtime availability.
Legacy controller/checkpoint models are converted explicitly during migration.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr, StringConstraints, model_validator

from aw2_lab.match_contract import (
    CheckpointReference,
    ContractModel,
    FixedMatchConfiguration,
    GameplayAction,
    MatchLifecycle,
    PlayerSlot,
    PlayerSlotState,
    Revision,
    SlotStatus,
)
from aw2_lab.match_contract import (
    MatchSummary as ControllerMatchSummary,
)
from aw2_lab.match_observation import MatchObservation

MAX_JSON_BYTES: Literal[65536] = 65536
MAX_PATH_COORDINATES: Literal[4096] = 4096
SecretToken = Annotated[SecretStr, Field(min_length=32, max_length=128, exclude=True, repr=False)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class PlayerConfiguration(ContractModel):
    slot: Literal["slot_1", "slot_2", "slot_3", "slot_4"]
    co_id: Identifier
    color: Literal["red", "blue", "green", "yellow", "black"]
    team_id: Literal["a", "b", "c", "d"]
    control: Literal["external", "computer"]


class RuleConfiguration(ContractModel):
    fog: bool = Field(strict=True)
    starting_weather: Literal["clear", "rain", "snow"]
    starting_funds: Annotated[int, Field(strict=True, ge=0, le=999999)]
    day_limit: Annotated[int, Field(strict=True, ge=1, le=99)]
    co_powers: bool = Field(strict=True)


class MatchConfiguration(ContractModel):
    """Complete requested configuration; support validation is a separate step."""

    map_id: Identifier
    players: Annotated[tuple[PlayerConfiguration, ...], Field(min_length=2, max_length=4)]
    rules: RuleConfiguration

    @model_validator(mode="after")
    def validate_assignments(self) -> MatchConfiguration:
        slots = [player.slot for player in self.players]
        if slots != [f"slot_{index}" for index in range(1, len(slots) + 1)]:
            raise ValueError("Players must use consecutive ordered slots starting at slot_1")
        if len({player.color for player in self.players}) != len(self.players):
            raise ValueError("Player colors must be unique")
        return self


VERIFIED_CONFIGURATION = MatchConfiguration(
    map_id="bean_island",
    players=(
        PlayerConfiguration(
            slot="slot_1", co_id="andy", color="red", team_id="a", control="external"
        ),
        PlayerConfiguration(
            slot="slot_2", co_id="max", color="blue", team_id="b", control="external"
        ),
    ),
    rules=RuleConfiguration(
        fog=False, starting_weather="clear", starting_funds=1000, day_limit=30, co_powers=True
    ),
)


class Request(ContractModel):
    request_id: UUID


class CreateMatchRequest(Request):
    # None means omitted: resolve once and persist the result for retry deduplication.
    configuration: MatchConfiguration | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if isinstance(value, dict) and "configuration" in value and value["configuration"] is None:
            raise ValueError("Provided configuration must be complete")
        return value


class RevisionRequest(Request):
    expected_revision: Revision


class GameplayCommandRequest(RevisionRequest):
    """Match and player identity come from the route and authenticated principal."""

    action: GameplayAction


class IssueInvitationRequest(Request):
    invitation_token: SecretToken
    expires_in_seconds: Annotated[int, Field(strict=True, ge=60, le=3600)] = 900


class JoinSlotRequest(Request):
    display_name: DisplayName
    invitation_token: SecretToken


class InvitationReference(ContractModel):
    invitation_id: UUID
    match_id: UUID
    player_slot: PlayerSlot
    expires_at: AwareDatetime


class OperatorPrincipal(ContractModel):
    """Trusted server-created identity; never construct from gameplay tool arguments."""

    kind: Literal["operator"] = "operator"
    authorization_generation: Annotated[int, Field(strict=True, ge=0)]


class PlayerPrincipal(ContractModel):
    kind: Literal["player"] = "player"
    match_id: UUID
    player_slot: PlayerSlot
    authorization_generation: Annotated[int, Field(strict=True, ge=0)]


Principal = Annotated[OperatorPrincipal | PlayerPrincipal, Field(discriminator="kind")]


class SlotAuthorization(ContractModel):
    """Public authorization metadata; no verifiers or invitation secrets."""

    match_id: UUID
    player_slot: PlayerSlot
    status: SlotStatus
    authorization_generation: Annotated[int, Field(strict=True, ge=0)]
    display_name: DisplayName | None = None

    @model_validator(mode="after")
    def validate_display_name(self) -> SlotAuthorization:
        if self.status is not SlotStatus.JOINED and self.display_name is not None:
            raise ValueError("Only joined slots have a display name")
        return self


class MatchSummary(ContractModel):
    match_id: UUID
    revision: Revision
    lifecycle: MatchLifecycle
    configuration: MatchConfiguration
    slots: tuple[PlayerSlotState, ...]
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_slots(self) -> MatchSummary:
        if tuple(slot.slot.value for slot in self.slots) != tuple(
            player.slot for player in self.configuration.players
        ):
            raise ValueError("Summary slots must match the configured ordered players")
        return self


class JoinSlotResponse(ContractModel):
    match: MatchSummary
    player_slot: PlayerSlot

    @model_validator(mode="after")
    def validate_joined_slot(self) -> JoinSlotResponse:
        if not any(
            slot.slot is self.player_slot and slot.status is SlotStatus.JOINED
            for slot in self.match.slots
        ):
            raise ValueError("Join response must identify a joined slot")
        return self


class MatchListResponse(ContractModel):
    matches: tuple[MatchSummary, ...]


class ObservationResponse(ContractModel):
    observation: MatchObservation


class StateResponse(ContractModel):
    summary: MatchSummary
    settled: bool
    observation: MatchObservation | None

    @model_validator(mode="after")
    def validate_coherence(self) -> StateResponse:
        if self.settled != (self.summary.lifecycle is not MatchLifecycle.EXECUTING):
            raise ValueError("Settled must agree with match lifecycle")
        if self.observation is not None and (
            self.observation.match_id != self.summary.match_id
            or self.observation.revision != self.summary.revision
        ):
            raise ValueError("Observation and summary must identify the same match and revision")
        return self


class ConfigurationProfile(ContractModel):
    profile_id: Identifier = "bean_island_v1"
    configuration: MatchConfiguration = VERIFIED_CONFIGURATION

    @model_validator(mode="after")
    def validate_verified_profile(self) -> ConfigurationProfile:
        if self.profile_id != "bean_island_v1" or self.configuration != VERIFIED_CONFIGURATION:
            raise ValueError("Only the verified bean_island_v1 profile can be advertised")
        return self


class ConfigurationOptions(ContractModel):
    """Accepted options derived from the verified profile, not the recognition catalog."""

    map_ids: tuple[Literal["bean_island"]] = ("bean_island",)
    co_ids: tuple[Literal["andy"], Literal["max"]] = ("andy", "max")
    players: tuple[PlayerConfiguration, ...] = VERIFIED_CONFIGURATION.players
    rules: RuleConfiguration = VERIFIED_CONFIGURATION.rules
    combination_constraint: Literal["verified_profiles_only"] = "verified_profiles_only"


class ApiLimits(ContractModel):
    json_bytes: Literal[65536] = MAX_JSON_BYTES
    path_coordinates: Literal[4096] = MAX_PATH_COORDINATES
    display_name_characters: Literal[80] = 80
    invitation_min_seconds: Literal[60] = 60
    invitation_max_seconds: Literal[3600] = 3600
    debug_max_frames: Literal[600] = 600
    debug_read_bytes: Literal[4096] = 4096
    debug_write_bytes: Literal[256] = 256
    event_replay_count: Literal[256] = 256
    event_replay_bytes: Literal[16777216] = 16777216
    subscriber_event_count: Literal[128] = 128
    subscriber_bytes: Literal[8388608] = 8388608
    heartbeat_seconds: Literal[15] = 15


class FeatureAvailability(ContractModel):
    name: Identifier
    implemented: bool
    available: bool
    verification: Literal[
        "unverified", "synthetic", "headless", "windowed", "headless_and_windowed"
    ]
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_available(self) -> FeatureAvailability:
        if self.available and not self.implemented:
            raise ValueError("An unimplemented feature cannot be available")
        if self.available == (self.unavailable_reason is not None):
            raise ValueError("Unavailable features require a reason; available features omit it")
        return self


class CapabilitiesResponse(ContractModel):
    supported_game_contract_versions: tuple[Literal[1], ...] = (1,)
    supported_player_counts: tuple[Literal[2], ...] = (2,)
    supported_control_modes: tuple[Literal["external"], ...] = ("external",)
    default_profile_id: Literal["bean_island_v1"] = "bean_island_v1"
    configuration_profiles: tuple[ConfigurationProfile] = (ConfigurationProfile(),)
    configuration_options: ConfigurationOptions = ConfigurationOptions()
    # Whole profiles are the combination constraint; catalogs do not imply a Cartesian product.
    operations: tuple[FeatureAvailability, ...] = ()
    actions: tuple[FeatureAvailability, ...] = ()
    http_sse: FeatureAvailability
    mcp_subscriptions: FeatureAvailability
    debug_enabled: bool = False
    limits: ApiLimits = ApiLimits()


class ReadinessState(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


class ReadinessResponse(ContractModel):
    http: Literal["ready"] = "ready"
    emulator: ReadinessState
    bridge: ReadinessState
    queue: ReadinessState
    recovery: Literal["not_required", "required", "in_progress"]
    match_id: UUID | None = None
    match_lifecycle: MatchLifecycle | None = None
    match_ready: bool = False


def configuration_from_controller(configuration: FixedMatchConfiguration) -> MatchConfiguration:
    """Losslessly translate old checkpoint shape, including non-default stored rules."""
    return VERIFIED_CONFIGURATION.model_copy(
        update={
            "rules": RuleConfiguration.model_validate(configuration.rules.model_dump()),
        }
    )


def summary_from_controller(summary: ControllerMatchSummary) -> MatchSummary:
    return MatchSummary(
        match_id=summary.match_id,
        revision=summary.revision,
        lifecycle=summary.lifecycle,
        configuration=configuration_from_controller(summary.configuration),
        slots=summary.slots,
        created_at=summary.created_at,
    )


class StartMatchRequest(RevisionRequest):
    pass


class CloseMatchRequest(Request):
    """Closing is ordered after prior work and has no expected game revision."""


class RevokeSlotRequest(Request):
    pass


class CreateCheckpointRequest(RevisionRequest):
    pass


class RestoreCheckpointRequest(RevisionRequest):
    pass


class DebugFramesRequest(RevisionRequest):
    frames: Annotated[int, Field(strict=True, ge=1, le=600)]


class DebugButtonsRequest(DebugFramesRequest):
    buttons: Annotated[
        tuple[
            Literal[
                "a", "b", "select", "start", "up", "down", "left", "right", "l", "r", "neutral"
            ],
            ...,
        ],
        Field(min_length=1, max_length=10),
    ]

    @model_validator(mode="after")
    def validate_buttons(self) -> DebugButtonsRequest:
        if len(set(self.buttons)) != len(self.buttons):
            raise ValueError("Button names must be unique")
        if "neutral" in self.buttons and len(self.buttons) != 1:
            raise ValueError("Neutral cannot be combined with pressed buttons")
        return self


class DebugResetRequest(RevisionRequest):
    pass


class DebugMemoryReadRequest(ContractModel):
    expected_revision: Revision
    address: Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]
    length: Annotated[int, Field(strict=True, ge=1, le=4096)]

    @model_validator(mode="after")
    def validate_range(self) -> DebugMemoryReadRequest:
        if self.address + self.length > 1 << 32:
            raise ValueError("Memory range exceeds the address space")
        return self


class DebugMemoryWriteRequest(RevisionRequest):
    address: Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]
    data: str = Field(min_length=4, max_length=344)

    @model_validator(mode="after")
    def validate_data(self) -> DebugMemoryWriteRequest:
        import base64
        import binascii

        try:
            decoded = base64.b64decode(self.data, validate=True)
        except ValueError, binascii.Error:
            raise ValueError("Memory data must be standard base64") from None
        if not 1 <= len(decoded) <= 256:
            raise ValueError("Memory writes require 1 to 256 bytes")
        if base64.b64encode(decoded).decode("ascii") != self.data:
            raise ValueError("Memory data must use canonical base64")
        if self.address + len(decoded) > 1 << 32:
            raise ValueError("Memory range exceeds the address space")
        return self


class DebugMemoryReadResponse(ContractModel):
    match_id: UUID
    revision: Revision
    frame: Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]
    address: Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]
    data: str


class CheckpointListResponse(ContractModel):
    checkpoints: tuple[CheckpointReference, ...]


class CheckpointCompatibility(ContractModel):
    """Safe metadata; excludes manifests' credential hashes and local paths."""

    rom_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    emulator_build: str = Field(min_length=1)
    emulator_mode: Literal["headless", "windowed"]
    decoder_schema_version: Annotated[int, Field(strict=True, ge=1)]
    observation_schema_version: Annotated[int, Field(strict=True, ge=1)]


class CheckpointResponse(ContractModel):
    checkpoint: CheckpointReference
    compatibility: CheckpointCompatibility
