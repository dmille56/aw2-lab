"""Move an APC and explicitly supply all adjacent allied units."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.aw2_unit_profiles import UNIT_PROFILES
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, ErrorCode, MatchLifecycle, SupplyAction
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
class SupplyActionExecutor:
    """Guard APC-only Supply, execute it, and verify all neighboring refills."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, SupplyAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only supply is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Supply requires a ready, identified player-turn observation",
            )
        identity = next(
            (item for item in observation.unit_identities if item.identity_id == action.unit_id),
            None,
        )
        apc = next(
            (
                unit
                for unit in battle.units
                if identity is not None and unit.reference == identity.reference
            ),
            None,
        )
        if (
            identity is None
            or apc is None
            or apc.army_slot != battle.active_player_slot
            or apc.used_this_turn
            or apc.embarked
            or apc.unit_type != 7
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Supply requires an unused allied APC")
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(apc.x, apc.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error
        endpoint = path[-1] if path else (apc.x, apc.y)
        if not any(
            unit.army_slot == apc.army_slot
            and not unit.embarked
            and unit.reference != apc.reference
            and abs(unit.x - endpoint[0]) + abs(unit.y - endpoint[1]) == 1
            for unit in battle.units
        ):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Supply requires an allied unit adjacent to the APC endpoint",
            )

        # Complete caller-controlled validation before emulator input.
        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None or selected_unit.unit_type != 7:
            raise RuntimeError("Selected unit was not the requested APC")
        ui_identity = (
            selected_unit.army_slot,
            selected_unit.unit_slot,
            selected_unit.unit_type,
            selected_unit.record_address,
        )
        await self.navigator.move_selected_unit_along_path(
            path,
            unit=ui_identity,
            width=battle.map.width,
            height=battle.map.height,
        )
        final_state = await self.navigator.choose_supply()
        final_battle = final_state.battle.value
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
        ):
            raise RuntimeError("Supply did not return to a recognized player-turn boundary")
        final_apc = next(
            (unit for unit in final_battle.units if unit.reference == apc.reference), None
        )
        if (
            final_apc is None
            or final_apc.unit_type != 7
            or (final_apc.x, final_apc.y) != endpoint
            or not final_apc.used_this_turn
        ):
            raise RuntimeError("Supply did not consume the requested APC at its planned endpoint")
        recipients = [
            unit
            for unit in final_battle.units
            if unit.army_slot == apc.army_slot
            and not unit.embarked
            and unit.reference != apc.reference
            and abs(unit.x - final_apc.x) + abs(unit.y - final_apc.y) == 1
        ]
        if not recipients or any(
            unit.fuel != UNIT_PROFILES[unit.unit_type].fuel_capacity
            or unit.ammo != UNIT_PROFILES[unit.unit_type].ammo_capacity
            for unit in recipients
        ):
            raise RuntimeError("Supply did not refill every adjacent allied unit to its capacity")
        return MutationOutcome(
            observation=self.tracker.commit_boundary(final_state),
            lifecycle=MatchLifecycle.PLAYABLE,
        )
