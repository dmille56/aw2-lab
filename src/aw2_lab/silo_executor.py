"""Guarded controller-input executor for missile silo launches."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    ErrorCode,
    MatchLifecycle,
    SiloLaunchAction,
)
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
class SiloLaunchActionExecutor:
    """Move an Infantry/Mech to an unused silo, target, and verify silo consumption."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, SiloLaunchAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Invalid missile silo action")
        game = observation.game_state
        battle = game.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Missile silo use requires a ready, identified player-turn observation",
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
        if (
            identity is None
            or unit is None
            or unit.unit_type not in (1, 2)
            or unit.army_slot != battle.active_player_slot
            or unit.used_this_turn
            or unit.embarked
        ):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Missile silo use requires an unused active-player Infantry or Mech",
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
        target = (action.target.x, action.target.y)
        if not (0 <= target[0] < battle.map.width and 0 <= target[1] < battle.map.height):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Missile target is outside the map")
        tile = next((tile for tile in battle.map.tiles if (tile.x, tile.y) == destination), None)
        if tile is None or tile.terrain_class != 17:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Missile silo use requires the route to end on an unused missile silo",
            )

        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None:
            raise RuntimeError("Selected silo unit was not present in its movement overlay")
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
        final_state = await self.navigator.choose_silo_launch(
            target,
            unit=unit_identity,
            width=battle.map.width,
            height=battle.map.height,
        )
        final_battle = final_state.battle.value
        final_unit = (
            next((item for item in final_battle.units if item.reference == unit.reference), None)
            if final_battle is not None
            else None
        )
        final_tile = (
            next(
                (item for item in final_battle.map.tiles if (item.x, item.y) == destination),
                None,
            )
            if final_battle is not None
            else None
        )
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_unit is None
            or (final_unit.x, final_unit.y) != destination
            or not final_unit.used_this_turn
            or final_tile is None
            or final_tile.terrain_class != 18
        ):
            raise RuntimeError("Missile silo launch did not reach its expected settled state")
        committed = self.tracker.commit_boundary(final_state)
        committed_unit = next(
            (item for item in committed.unit_identities if item.reference == unit.reference), None
        )
        if committed_unit is None or committed_unit.identity_id != action.unit_id:
            self.tracker.mark_uncertain("Unit identity changed during missile silo launch")
            raise RuntimeError("Missile silo launch changed the unit's lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
