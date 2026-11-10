"""Controller-input executor for merging an active unit with an allied unit."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, ErrorCode, JoinAction, MatchLifecycle
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
class JoinActionExecutor:
    """Move onto the named same-type ally, Join, and verify the merge."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, JoinAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only join is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Join requires a ready, identified player-turn observation",
            )
        source_identity = next(
            (item for item in observation.unit_identities if item.identity_id == action.unit_id),
            None,
        )
        source = next(
            (
                unit
                for unit in battle.units
                if source_identity is not None and unit.reference == source_identity.reference
            ),
            None,
        )
        if (
            source_identity is None
            or source is None
            or source.army_slot != battle.active_player_slot
            or source.used_this_turn
            or source.embarked
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Joining unit is unavailable")
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(source.x, source.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error
        destination = path[-1] if path else (source.x, source.y)
        if destination == (source.x, source.y):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Join requires a destination ally")
        partner = next(
            (
                unit
                for unit in battle.units
                if (unit.x, unit.y) == destination
                and unit.reference != source.reference
                and not unit.embarked
            ),
            None,
        )
        if (
            partner is None
            or partner.army_slot != source.army_slot
            or partner.unit_type != source.unit_type
            or partner.used_this_turn
        ):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Join destination must contain an unused allied unit of the same type",
            )
        partner_identity = next(
            (item for item in observation.unit_identities if item.reference == partner.reference),
            None,
        )
        if partner_identity is None:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE, "Join partner identity is unavailable"
            )

        # Caller-controlled checks finish before the first emulator input.
        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None:
            raise RuntimeError("Selected unit was not present in the movement overlay")
        acting_ui_identity = (
            selected_unit.army_slot,
            selected_unit.unit_slot,
            selected_unit.unit_type,
            selected_unit.record_address,
        )
        await self.navigator.move_selected_unit_along_path(
            path,
            unit=acting_ui_identity,
            width=battle.map.width,
            height=battle.map.height,
        )
        final_state = await self.navigator.choose_join()
        final_battle = final_state.battle.value
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
        ):
            raise RuntimeError("Join did not return to a recognized player-turn boundary")
        final_source = next(
            (item for item in final_battle.units if item.reference == source.reference), None
        )
        final_partner = next(
            (item for item in final_battle.units if item.reference == partner.reference), None
        )
        if (
            final_source is None
            or final_source.unit_type != source.unit_type
            or (final_source.x, final_source.y) != destination
            or not final_source.used_this_turn
            or final_source.internal_health <= source.internal_health
            or final_partner is not None
        ):
            raise RuntimeError("Join did not preserve the mover and consume the named partner")

        committed = self.tracker.commit_boundary(final_state)
        committed_source = next(
            (item for item in committed.unit_identities if item.reference == source.reference),
            None,
        )
        if committed_source is None or committed_source.identity_id != action.unit_id:
            self.tracker.mark_uncertain("Unit lifetime identity changed during Join")
            raise RuntimeError("Join changed the moving unit's lifetime identity")
        if any(item.reference == partner.reference for item in committed.unit_identities):
            self.tracker.mark_uncertain("Joined partner identity remained after Join")
            raise RuntimeError("Join did not remove the named partner's lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
