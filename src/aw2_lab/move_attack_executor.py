"""Controller-input executor for moving a unit and attacking one target."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.aw2_unit_profiles import preflight_move_attack
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    ErrorCode,
    MatchLifecycle,
    MoveAttackAction,
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

_TERMINAL_PHASES = frozenset(
    {
        LifecyclePhase.RESULT_SEQUENCE,
        LifecyclePhase.VICTORY_PRESENTATION,
        LifecyclePhase.DEFEAT_PRESENTATION,
        LifecyclePhase.RESULT_SUMMARY,
        LifecyclePhase.SAVE_PROGRESS_PROMPT,
    }
)


@dataclass(slots=True)
class MoveAttackActionExecutor:
    """Execute movement, Fire targeting, combat, and result verification."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, MoveAttackAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only move_attack is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Move and Attack requires a ready, identified player-turn observation",
            )
        attacker_identity = next(
            (item for item in observation.unit_identities if item.identity_id == action.unit_id),
            None,
        )
        attacker = next(
            (
                unit
                for unit in battle.units
                if attacker_identity is not None and unit.reference == attacker_identity.reference
            ),
            None,
        )
        if (
            attacker_identity is None
            or attacker is None
            or attacker.army_slot != battle.active_player_slot
            or attacker.used_this_turn
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Attacking unit is unavailable")
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(attacker.x, attacker.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error

        target_coordinate = (action.target.x, action.target.y)
        if not (
            0 <= target_coordinate[0] < battle.map.width
            and 0 <= target_coordinate[1] < battle.map.height
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Attack target is outside the map")
        target = next(
            (
                unit
                for unit in battle.units
                if (unit.x, unit.y) == target_coordinate
                and unit.army_slot != battle.active_player_slot
                and not unit.embarked
            ),
            None,
        )
        if target is None:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST, "No opposing unit is observed at target"
            )

        terrain_by_tile = {(tile.x, tile.y): tile.terrain_class for tile in battle.map.tiles}
        try:
            preflight_move_attack(
                unit_type=attacker.unit_type,
                ammo=attacker.ammo,
                path=path,
                start=(attacker.x, attacker.y),
                target=target_coordinate,
                target_unit_type=target.unit_type,
                terrain_classes=tuple(terrain_by_tile[point] for point in path),
            )
        except ValueError as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error

        # AW2 remains authoritative about terrain, fog, weather, and weapon matchup.
        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None:
            raise RuntimeError("Attacking unit was not present in the movement overlay")
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
        await self.navigator.choose_fire()
        await self.navigator.move_target_cursor_to(
            *target_coordinate,
            width=battle.map.width,
            height=battle.map.height,
        )
        resolved = await self.navigator.confirm_attack()

        if resolved.lifecycle.phase in _TERMINAL_PHASES:
            committed = self.tracker.commit_terminal_boundary(resolved)
            return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.FINISHED)

        final_battle = resolved.battle.value
        if (
            resolved.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or resolved.ui.menu.family is not MenuFamily.MAP_INPUT
            or resolved.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
        ):
            raise RuntimeError("Attack did not return to a recognized player-turn boundary")
        final_attacker = next(
            (unit for unit in final_battle.units if unit.reference == attacker.reference), None
        )
        final_target = next(
            (unit for unit in final_battle.units if unit.reference == target.reference), None
        )
        allowed_positions = {(attacker.x, attacker.y), *path}
        if final_attacker is not None and (
            final_attacker.unit_type != attacker.unit_type
            or (final_attacker.x, final_attacker.y) not in allowed_positions
            or not final_attacker.used_this_turn
        ):
            raise RuntimeError("Attacking unit did not reach the expected post-attack state")
        target_resolved = final_target is None or (
            final_target.unit_type == target.unit_type
            and final_target.army_slot == target.army_slot
            and (final_target.x, final_target.y) == target_coordinate
        )
        if not target_resolved:
            raise RuntimeError("Attack returned to control without a verified target change")

        committed = self.tracker.commit_boundary(resolved)
        if final_attacker is not None:
            committed_attacker = next(
                (
                    item
                    for item in committed.unit_identities
                    if item.reference == attacker.reference
                ),
                None,
            )
            if committed_attacker is None or committed_attacker.identity_id != action.unit_id:
                self.tracker.mark_uncertain("Attacker lifetime identity changed during combat")
                raise RuntimeError("Attack changed the acting unit's lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
