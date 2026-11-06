"""Controller-input executors for verified transport loading and unloading."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    ErrorCode,
    LoadAction,
    MatchLifecycle,
    UnloadAction,
)
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.state_model import ValueStatus
from aw2_lab.transport_rules import can_carry, free_capacity
from aw2_lab.ui_state import MenuFamily, MenuItem


@dataclass(slots=True)
class LoadActionExecutor:
    """Move one compatible unit onto an allied carrier and verify cargo state."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, LoadAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only load is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Load requires a ready, identified player-turn observation",
            )
        identities = {unit.identity_id: unit for unit in observation.unit_identities}
        cargo_identity = identities.get(action.unit_id)
        transport_identity = identities.get(action.transport_id)
        cargo = next(
            (
                unit
                for unit in battle.units
                if cargo_identity and unit.reference == cargo_identity.reference
            ),
            None,
        )
        transport = next(
            (
                unit
                for unit in battle.units
                if transport_identity and unit.reference == transport_identity.reference
            ),
            None,
        )
        if (
            cargo is None
            or transport is None
            or cargo_identity is None
            or transport_identity is None
            or cargo.reference == transport.reference
            or cargo.army_slot != battle.active_player_slot
            or transport.army_slot != battle.active_player_slot
            or cargo.used_this_turn
            or cargo.embarked
            or transport.embarked
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Cargo unit or carrier is unavailable")
        if not can_carry(transport.unit_type, cargo.unit_type):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Carrier cannot carry this unit type")
        if free_capacity(transport) < 1:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Carrier has no free cargo capacity")
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(cargo.x, cargo.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error
        if (path[-1] if path else (cargo.x, cargo.y)) != (transport.x, transport.y):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST, "Load route must end on the allied carrier's tile"
            )

        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if (
            selected_unit is None
            or selected_unit.army_slot != cargo.army_slot
            or selected_unit.unit_slot != cargo.unit_slot
            or selected_unit.unit_type != cargo.unit_type
        ):
            raise RuntimeError("Selected cargo unit does not match the committed identity")
        expected = (
            selected_unit.army_slot,
            selected_unit.unit_slot,
            selected_unit.unit_type,
            selected_unit.record_address,
        )
        menu_state = await self.navigator.move_selected_unit_along_path(
            path,
            unit=expected,
            width=battle.map.width,
            height=battle.map.height,
        )
        if (
            menu_state.ui.menu.family is not MenuFamily.UNIT_ACTION_CHOICES
            or MenuItem.LOAD not in menu_state.ui.menu.items
        ):
            raise RuntimeError("The observed unit action menu did not offer Load")
        final_state = await self.navigator.choose_load()
        final_battle = final_state.battle.value
        final_cargo = (
            next((item for item in final_battle.units if item.reference == cargo.reference), None)
            if final_battle is not None
            else None
        )
        final_transport = (
            next(
                (item for item in final_battle.units if item.reference == transport.reference), None
            )
            if final_battle is not None
            else None
        )
        if (
            final_state.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
            or final_cargo is None
            or final_transport is None
            or not final_cargo.embarked
            or not final_cargo.used_this_turn
            or cargo.reference not in final_transport.cargo_references
        ):
            raise RuntimeError("Load did not produce the expected embarked cargo state")
        committed = self.tracker.commit_boundary(final_state)
        committed_ids = {unit.reference: unit.identity_id for unit in committed.unit_identities}
        if (
            committed_ids.get(cargo.reference) != action.unit_id
            or committed_ids.get(transport.reference) != action.transport_id
        ):
            self.tracker.mark_uncertain("Unit identities changed while committing the Load result")
            raise RuntimeError("Unit identities changed while committing the Load result")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)


@dataclass(slots=True)
class UnloadActionExecutor:
    """Fail closed until the drop cursor and sequential cargo flow are verified."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        if isinstance(request.action, UnloadAction):
            raise CommandRejected(
                ErrorCode.UNSUPPORTED_FEATURE,
                "Unloading is unavailable until legal drop selection is verified",
            )
        raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only unload is supported")
