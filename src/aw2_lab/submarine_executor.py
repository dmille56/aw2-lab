"""Controller-input executor for Sub Dive and Rise orders."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, DiveAction, ErrorCode, MatchLifecycle, RiseAction
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.state_model import ValueStatus
from aw2_lab.ui_state import MenuFamily


@dataclass(slots=True)
class SubmarineModeActionExecutor:
    """Move a Sub, change its surface mode, and verify the settled state."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker
    submerged_after_action: bool

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        action_type = DiveAction if self.submerged_after_action else RiseAction
        if not isinstance(action, action_type):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Invalid Sub mode action")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Dive and Rise require a ready, identified player-turn observation",
            )
        identity = next(
            (item for item in observation.unit_identities if item.identity_id == action.unit_id),
            None,
        )
        unit = next(
            (
                candidate
                for candidate in battle.units
                if identity is not None and candidate.reference == identity.reference
            ),
            None,
        )
        expected_before = not self.submerged_after_action
        if (
            identity is None
            or unit is None
            or unit.unit_type != 24
            or unit.army_slot != battle.active_player_slot
            or unit.used_this_turn
            or unit.embarked
            or unit.submerged != expected_before
        ):
            mode = "submerged" if expected_before else "surfaced"
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                f"{action_type.__name__.removesuffix('Action')} requires an unused {mode} Sub",
            )
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(unit.x, unit.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error
        destination = path[-1] if path else (unit.x, unit.y)

        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None:
            raise RuntimeError("Selected Sub was not present in its movement overlay")
        unit_identity = (
            selected_unit.army_slot,
            selected_unit.unit_slot,
            selected_unit.unit_type,
            selected_unit.record_address,
        )
        await self.navigator.move_selected_unit_along_path(
            path,
            unit=unit_identity,
            width=battle.map.width,
            height=battle.map.height,
        )
        final_state = (
            await self.navigator.choose_dive()
            if self.submerged_after_action
            else await self.navigator.choose_rise()
        )
        final_battle = final_state.battle.value
        final_unit = (
            next((item for item in final_battle.units if item.reference == unit.reference), None)
            if final_battle is not None
            else None
        )
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_unit is None
            or final_unit.unit_type != 24
            or (final_unit.x, final_unit.y) != destination
            or not final_unit.used_this_turn
            or final_unit.submerged != self.submerged_after_action
        ):
            raise RuntimeError("Sub Dive/Rise did not reach the expected settled unit state")

        committed = self.tracker.commit_boundary(final_state)
        committed_unit = next(
            (item for item in committed.unit_identities if item.reference == unit.reference), None
        )
        if committed_unit is None or committed_unit.identity_id != action.unit_id:
            self.tracker.mark_uncertain("Sub identity changed during Dive/Rise")
            raise RuntimeError("Sub Dive/Rise changed the unit's lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)


@dataclass(slots=True)
class DiveActionExecutor(SubmarineModeActionExecutor):
    """Executor bound to Dive's surfaced-to-submerged transition."""

    submerged_after_action: bool = True


@dataclass(slots=True)
class RiseActionExecutor(SubmarineModeActionExecutor):
    """Executor bound to Rise's submerged-to-surfaced transition."""

    submerged_after_action: bool = False
