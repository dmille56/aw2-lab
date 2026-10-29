"""Controller-input executor for one explicit movement followed by Wait."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    ErrorCode,
    MatchLifecycle,
    MoveWaitAction,
)
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.state_model import ValueStatus


@dataclass(slots=True)
class MoveWaitActionExecutor:
    """Execute and verify the currently supported move-then-Wait command."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, MoveWaitAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only move_wait is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Move and Wait requires a ready, identified player-turn observation",
            )
        identity = next(
            (unit for unit in observation.unit_identities if unit.identity_id == action.unit_id),
            None,
        )
        unit = next(
            (
                unit
                for unit in battle.units
                if identity is not None and unit.reference == identity.reference
            ),
            None,
        )
        if (
            identity is None
            or unit is None
            or unit.army_slot != battle.active_player_slot
            or unit.used_this_turn
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Unit is unavailable for this action")
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(unit.x, unit.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error

        # All caller-controlled rejection happens before the first emulator input.
        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None:
            raise RuntimeError("Selected unit was not present in the movement overlay")
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
        final_state = await self.navigator.choose_wait()

        final_battle = final_state.battle.value
        final_unit = (
            next(
                (
                    candidate
                    for candidate in final_battle.units
                    if candidate.reference == unit.reference
                ),
                None,
            )
            if final_battle is not None
            else None
        )
        expected_position = path[-1] if path else (unit.x, unit.y)
        if (
            final_battle is None
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_unit is None
            or final_unit.unit_type != unit.unit_type
            or (final_unit.x, final_unit.y) != expected_position
            or not final_unit.used_this_turn
        ):
            raise RuntimeError("Move and Wait final state did not match the requested action")

        committed = self.tracker.commit_boundary(final_state)
        committed_identity = next(
            (item for item in committed.unit_identities if item.reference == unit.reference), None
        )
        if committed_identity is None or committed_identity.identity_id != action.unit_id:
            self.tracker.mark_uncertain("Unit lifetime identity changed during Move and Wait")
            raise RuntimeError("Move and Wait changed the acting unit's lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
