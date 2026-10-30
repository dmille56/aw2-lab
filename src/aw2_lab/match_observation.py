"""Match identity, revisions, and unit lifetimes around pure game-state decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.state_model import (
    GAME_STATE_SCHEMA_VERSION,
    GameState,
    ValueStatus,
)
from aw2_lab.ui_state import CursorStatus, MenuFamily
from aw2_lab.unit_identity import (
    IDENTITY_SCHEMA_VERSION,
    UnitIdentityMetadata,
    UnitIdentityTracker,
    UnitObservation,
)

MATCH_OBSERVATION_SCHEMA_VERSION = 1
MAX_MATCH_REVISION = (1 << 53) - 1


class ActionReadiness(StrEnum):
    """Whether the current observation supports beginning a gameplay command."""

    READY = "ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class IdentityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class UnitIdentityObservation:
    """Public lifetime identity keyed by the decoder's reusable unit reference."""

    reference: int
    identity_id: str
    generation: int


class RevisionCause(StrEnum):
    COMMAND = "command"
    DEBUG_MUTATION = "debug_mutation"
    ROLLBACK = "rollback"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class MatchObservation:
    """A committed state with its match/revision and lifetime unit IDs."""

    match_id: UUID
    revision: int
    game_state: GameState
    unit_identities: tuple[UnitIdentityObservation, ...]
    identity_status: IdentityStatus
    identity_reasons: tuple[str, ...]
    action_readiness: ActionReadiness
    action_readiness_reasons: tuple[str, ...]
    schema_version: int = MATCH_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MATCH_OBSERVATION_SCHEMA_VERSION:
            raise ValueError(f"Unsupported match-observation schema: {self.schema_version}")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError("Match revision must be an integer")
        if not 0 <= self.revision <= MAX_MATCH_REVISION:
            raise ValueError("Match revision must fit a JavaScript safe integer")
        if self.identity_status is IdentityStatus.AVAILABLE:
            battle = self.game_state.battle.value
            if battle is None or self.game_state.battle.status is not ValueStatus.AVAILABLE:
                raise ValueError("Available unit identities require available battle data")
            if len(self.unit_identities) != len(battle.units) or {
                item.reference for item in self.unit_identities
            } != {unit.reference for unit in battle.units}:
                raise ValueError("Every active unit must have exactly one lifetime identity")
            if len({item.identity_id for item in self.unit_identities}) != len(
                self.unit_identities
            ):
                raise ValueError("Active units must have distinct lifetime identities")
            if any(
                isinstance(item.reference, bool)
                or not isinstance(item.reference, int)
                or not item.identity_id.isdecimal()
                or int(item.identity_id) < 1
                or isinstance(item.generation, bool)
                or not isinstance(item.generation, int)
                or item.generation < 1
                for item in self.unit_identities
            ):
                raise ValueError("Unit lifetime IDs and generations must be positive")
        elif not self.identity_reasons:
            raise ValueError("Unavailable unit identities require a reason")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible, versioned document."""
        return {
            "schema_version": self.schema_version,
            "match_id": str(self.match_id),
            "revision": self.revision,
            "game_state": self.game_state.to_dict(),
            "unit_identities": [asdict(item) for item in self.unit_identities],
            "identity_status": self.identity_status.value,
            "identity_reasons": list(self.identity_reasons),
            "action_readiness": self.action_readiness.value,
            "action_readiness_reasons": list(self.action_readiness_reasons),
        }


@dataclass(frozen=True, slots=True)
class MatchObservationMetadata:
    """Match revision and unit-lifetime ledger stored with a checkpoint."""

    match_id: UUID
    revision: int
    last_frame: int
    identity_metadata: UnitIdentityMetadata
    schema_version: int = MATCH_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MATCH_OBSERVATION_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported match-observation metadata schema: {self.schema_version}"
            )
        _validate_revision(self.revision)
        if isinstance(self.last_frame, bool) or not isinstance(self.last_frame, int):
            raise TypeError("Checkpoint frame must be an integer")
        if not 0 <= self.last_frame < 1 << 32:
            raise ValueError("Checkpoint frame must fit the bridge's unsigned 32-bit frame")
        if self.identity_metadata.schema_version != IDENTITY_SCHEMA_VERSION:
            raise ValueError("Checkpoint unit-identity schema is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "match_id": str(self.match_id),
            "revision": self.revision,
            "last_frame": self.last_frame,
            "identity_metadata": self.identity_metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> MatchObservationMetadata:
        if not isinstance(value, Mapping):
            raise TypeError("Match-observation metadata must be an object")
        try:
            match_id = UUID(_required_string(value, "match_id"))
        except ValueError as error:
            raise ValueError("Match-observation metadata match_id must be a UUID") from error
        identity = value.get("identity_metadata")
        return cls(
            match_id=match_id,
            revision=_required_int(value, "revision"),
            last_frame=_required_int(value, "last_frame"),
            identity_metadata=UnitIdentityMetadata.from_dict(identity),
            schema_version=_required_int(value, "schema_version"),
        )


class MatchObservationTracker:
    """Publish immutable command-boundary states without advancing on reads.

    The decoder remains stateless. Call ``commit_boundary`` only after the
    controller has reached a settled, validated boundary. A read returns the
    committed object and never calls the emulator or reconciles unit identities.
    """

    def __init__(
        self,
        match_id: UUID,
        *,
        revision: int = 0,
        identity_tracker: UnitIdentityTracker | None = None,
    ) -> None:
        _validate_revision(revision)
        self.match_id = match_id
        self._revision = revision
        self._identities = identity_tracker or UnitIdentityTracker()
        self._last_frame: int | None = None
        self._current: MatchObservation | None = None
        self._restore_pending = False
        self._continuity_error: str | None = None

    @classmethod
    def from_checkpoint(
        cls,
        metadata: MatchObservationMetadata,
        *,
        durable_revision_floor: int,
    ) -> MatchObservationTracker:
        """Restore IDs and advance beyond the persisted journal high-water mark.

        The floor must come from durable match/journal metadata, not from the
        checkpoint alone, because restoring an older checkpoint may otherwise
        reissue a revision already observed by a client before process restart.
        """
        _validate_revision(durable_revision_floor)
        if durable_revision_floor < metadata.revision:
            raise ValueError("Durable revision floor cannot precede the checkpoint revision")
        if durable_revision_floor == MAX_MATCH_REVISION:
            raise ValueError("Match revision space is exhausted")
        tracker = cls(
            metadata.match_id,
            revision=durable_revision_floor + 1,
            identity_tracker=UnitIdentityTracker.from_checkpoint(metadata.identity_metadata),
        )
        tracker._last_frame = metadata.last_frame
        tracker._restore_pending = True
        return tracker

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def continuity_valid(self) -> bool:
        return self._continuity_error is None

    def mark_uncertain(self, reason: str) -> None:
        """Stop publishing state after an unrecognized or incomplete mutation."""
        if not reason.strip():
            raise ValueError("Continuity failure requires a diagnostic reason")
        self._continuity_error = reason
        self._current = None

    def commit_boundary(
        self,
        game_state: GameState,
        *,
        cause: RevisionCause = RevisionCause.COMMAND,
    ) -> MatchObservation:
        """Publish one coherent boundary and advance its monotonic revision."""
        if self._continuity_error is not None:
            raise RuntimeError(
                "Unit identity continuity is unknown; restore a checkpoint before publishing"
            )
        if self._restore_pending and cause not in {RevisionCause.RESTORE, RevisionCause.ROLLBACK}:
            raise ValueError("Checkpoint load requires cause=RESTORE or cause=ROLLBACK")
        if game_state.schema_version != GAME_STATE_SCHEMA_VERSION:
            raise ValueError("GameState schema does not match this observer")
        if game_state.battle.status is not ValueStatus.AVAILABLE or game_state.battle.value is None:
            self.mark_uncertain("Boundary has no validated live battle data")
            raise ValueError("Command boundaries require validated live battle data")
        if game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
            self.mark_uncertain(
                f"Boundary lifecycle is {game_state.lifecycle.phase.value}, not a settled player turn"
            )
            raise ValueError("Command boundaries require a settled player turn")
        if (
            self._last_frame is not None
            and cause is RevisionCause.COMMAND
            and game_state.frame <= self._last_frame
        ):
            raise ValueError("Command boundary frame must advance beyond the last commit")
        next_revision = self._revision
        if not self._restore_pending:
            if next_revision == MAX_MATCH_REVISION:
                raise ValueError("Match revision space is exhausted")
            next_revision += 1

        battle = game_state.battle.value
        next_identity_tracker = UnitIdentityTracker.from_checkpoint(
            self._identities.checkpoint_metadata()
        )
        identity_by_reference = next_identity_tracker.reconcile(
            UnitObservation(
                reference=unit.reference,
                unit_type=unit.unit_type,
                x=unit.x,
                y=unit.y,
            )
            for unit in battle.units
        )
        unit_identities = tuple(
            UnitIdentityObservation(
                reference=unit.reference,
                identity_id=str(identity_by_reference[unit.reference].identity_id),
                generation=identity_by_reference[unit.reference].generation,
            )
            for unit in battle.units
        )
        readiness, readiness_reasons = _action_readiness(game_state)
        observation = MatchObservation(
            match_id=self.match_id,
            revision=next_revision,
            game_state=game_state,
            unit_identities=unit_identities,
            identity_status=IdentityStatus.AVAILABLE,
            identity_reasons=(),
            action_readiness=readiness,
            action_readiness_reasons=readiness_reasons,
        )
        self._revision = next_revision
        self._identities = next_identity_tracker
        self._last_frame = game_state.frame
        self._current = observation
        self._restore_pending = False
        return observation

    def commit_terminal_boundary(self, game_state: GameState) -> MatchObservation:
        """Publish a recognized result screen without reusing stale battle data."""
        terminal_phases = {
            LifecyclePhase.RESULT_SEQUENCE,
            LifecyclePhase.VICTORY_PRESENTATION,
            LifecyclePhase.DEFEAT_PRESENTATION,
            LifecyclePhase.RESULT_SUMMARY,
            LifecyclePhase.SAVE_PROGRESS_PROMPT,
        }
        if game_state.lifecycle.phase not in terminal_phases:
            raise ValueError("Terminal boundaries require a recognized result phase")
        if game_state.battle.status is ValueStatus.AVAILABLE or game_state.battle.value is not None:
            raise ValueError("Terminal boundaries must not publish retained live battle data")
        if self._restore_pending:
            raise ValueError("Checkpoint load must be completed before publishing a result")
        if self._last_frame is not None and game_state.frame <= self._last_frame:
            raise ValueError("Terminal boundary frame must advance beyond the last commit")
        if self._revision == MAX_MATCH_REVISION:
            raise ValueError("Match revision space is exhausted")
        observation = MatchObservation(
            match_id=self.match_id,
            revision=self._revision + 1,
            game_state=game_state,
            unit_identities=(),
            identity_status=IdentityStatus.UNAVAILABLE,
            identity_reasons=("Match has reached a recognized terminal result phase",),
            action_readiness=ActionReadiness.UNKNOWN,
            action_readiness_reasons=("The match is finished",),
        )
        self._revision = observation.revision
        self._last_frame = game_state.frame
        self._current = observation
        return observation

    def read(self) -> MatchObservation:
        """Return the last committed observation without emulator or ledger changes."""
        if self._current is None:
            raise RuntimeError("No committed match observation is available")
        return self._current

    def checkpoint_metadata(self) -> MatchObservationMetadata:
        """Snapshot identity and revision metadata beside emulator checkpoint data."""
        if self._last_frame is None:
            raise RuntimeError("Cannot checkpoint before the first committed boundary")
        return MatchObservationMetadata(
            match_id=self.match_id,
            revision=self._revision,
            last_frame=self._last_frame,
            identity_metadata=self._identities.checkpoint_metadata(),
        )


def _action_readiness(state: GameState) -> tuple[ActionReadiness, tuple[str, ...]]:
    if state.battle.status is not ValueStatus.AVAILABLE:
        return ActionReadiness.UNKNOWN, ("Live battle data is unavailable",)
    if state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN:
        return ActionReadiness.BLOCKED, ("Lifecycle is not a player turn",)
    if state.ui.menu.family is MenuFamily.UNRESOLVED:
        return ActionReadiness.UNKNOWN, ("Current menu is unresolved",)
    if state.ui.menu.actionable is False:
        return ActionReadiness.BLOCKED, ("Current menu choice is not actionable",)
    if state.ui.menu.family in {MenuFamily.INTEL, MenuFamily.OPTIONS}:
        return ActionReadiness.BLOCKED, ("Current submenu does not accept gameplay actions",)
    if state.ui.menu.family is MenuFamily.MAP_INPUT:
        if state.ui.map_cursor.status is CursorStatus.AVAILABLE:
            return ActionReadiness.READY, (
                "Map input is recognized; individual action legality is not predicted",
            )
        return ActionReadiness.UNKNOWN, ("Map cursor is not available",)
    if state.ui.menu.family is MenuFamily.UNIT_ACTION:
        if state.ui.menu.selected_unit is not None:
            return ActionReadiness.READY, (
                "Selected unit is recognized; individual action legality is not predicted",
            )
        return ActionReadiness.UNKNOWN, ("Selected unit is not verified",)
    if state.ui.menu.actionable is True:
        return ActionReadiness.READY, (
            "Input boundary is recognized; individual action legality is not predicted",
        )
    return ActionReadiness.UNKNOWN, ("Current input boundary is not verified",)


@dataclass(frozen=True, slots=True)
class ScreenshotReference:
    """Frame/revision association for a screenshot captured without state mutation."""

    match_id: UUID
    revision: int
    frame: int
    mime_type: str = "image/png"

    @classmethod
    def for_observation(cls, observation: MatchObservation) -> ScreenshotReference:
        return cls(
            match_id=observation.match_id,
            revision=observation.revision,
            frame=observation.game_state.frame,
        )


def _validate_revision(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Match revision must be an integer")
    if not 0 <= value <= MAX_MATCH_REVISION:
        raise ValueError("Match revision must fit a JavaScript safe integer")


def _required_int(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise TypeError(f"Match-observation metadata {name} must be an integer")
    return result


def _required_string(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise TypeError(f"Match-observation metadata {name} must be a string")
    return result
