"""Controller-input executors for verified transport loading and unloading."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.aw2_unit_profiles import (
    BASELINE_RULES,
    UNIT_PROFILES,
    RuleContext,
    movement_cost,
)
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
from aw2_lab.transport_rules import TRANSPORT_CAPACITY, can_carry, free_capacity, is_transport
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
    """Move a carrier, unload requested cargo in AW2's link order, and verify state."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, UnloadAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only unload is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Unload requires a ready, identified player-turn observation",
            )

        identities = {unit.identity_id: unit for unit in observation.unit_identities}
        carrier_identity = identities.get(action.transport_id)
        carrier = next(
            (
                unit
                for unit in battle.units
                if carrier_identity and unit.reference == carrier_identity.reference
            ),
            None,
        )
        if (
            carrier is None
            or carrier_identity is None
            or carrier.army_slot != battle.active_player_slot
            or carrier.used_this_turn
            or carrier.embarked
            or not is_transport(carrier.unit_type)
            or not carrier.cargo_references
            or len(carrier.cargo_references) > TRANSPORT_CAPACITY[carrier.unit_type]
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Carrier is unavailable for unloading")
        try:
            path = validate_path(
                tuple((point.x, point.y) for point in action.path),
                start=(carrier.x, carrier.y),
                width=battle.map.width,
                height=battle.map.height,
            )
        except (TypeError, ValueError) as error:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, str(error)) from error

        cargo_by_reference = {unit.reference: unit for unit in battle.units}
        identity_by_reference = {unit.reference: unit for unit in observation.unit_identities}
        linked_cargo = []
        for reference in carrier.cargo_references:
            cargo = cargo_by_reference.get(reference)
            identity = identity_by_reference.get(reference)
            if (
                cargo is None
                or identity is None
                or not cargo.embarked
                or cargo.army_slot != carrier.army_slot
                or not can_carry(carrier.unit_type, cargo.unit_type)
            ):
                raise CommandRejected(
                    ErrorCode.OBSERVATION_UNAVAILABLE,
                    "Carrier cargo links are incomplete or inconsistent",
                )
            linked_cargo.append((cargo, identity.identity_id))
        requested_ids = tuple(drop.unit_id for drop in action.drops)
        if len(set(requested_ids)) != len(requested_ids):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST, "A cargo unit may be dropped only once"
            )
        ordered_ids = tuple(identity_id for _, identity_id in linked_cargo)
        if requested_ids != ordered_ids[: len(requested_ids)]:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Cargo must be dropped in the carrier's observed order",
            )

        final_carrier_position = path[-1] if path else (carrier.x, carrier.y)
        tile_by_position = {(tile.x, tile.y): tile for tile in battle.map.tiles}
        occupied = {
            (unit.x, unit.y)
            for unit in battle.units
            if not unit.embarked and unit.reference != carrier.reference
        }
        if (
            battle.weather.status is not ValueStatus.AVAILABLE
            or battle.weather.value is None
            or battle.co_effects_enabled.status is not ValueStatus.AVAILABLE
            or battle.co_effects_enabled.value is None
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Weather and CO movement settings are required to validate drop terrain",
            )
        player = next(
            (item for item in battle.players if item.slot == battle.active_player_slot), None
        )
        if player is None:
            raise CommandRejected(ErrorCode.OBSERVATION_UNAVAILABLE, "Active player is unavailable")
        context = (
            BASELINE_RULES
            if battle.co_effects_enabled.value is False
            else RuleContext(player.co_id, player.active_power)
        )
        for cargo_entry, drop in zip(linked_cargo, action.drops, strict=False):
            cargo_unit = cargo_entry[0]
            destination = (drop.destination.x, drop.destination.y)
            tile = tile_by_position.get(destination)
            if tile is None:
                raise CommandRejected(
                    ErrorCode.INVALID_REQUEST, "Drop destination is outside the map"
                )
            if destination == final_carrier_position or destination in occupied:
                raise CommandRejected(ErrorCode.INVALID_REQUEST, "Drop destination is occupied")
            try:
                cost = movement_cost(
                    tile.terrain_class,
                    UNIT_PROFILES[cargo_unit.unit_type].movement_type,
                    battle.weather.value,
                    context=context,
                )
            except (KeyError, ValueError) as error:
                raise CommandRejected(
                    ErrorCode.INVALID_REQUEST, "Drop terrain is unsupported"
                ) from error
            if cost is None:
                raise CommandRejected(
                    ErrorCode.INVALID_REQUEST,
                    f"Terrain at {destination} is impassable for {cargo_unit.unit_type}",
                )
            occupied.add(destination)

        # All request-controlled validation is complete before the first input.
        selected = await self.navigator.select_unit(action.transport_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if (
            selected_unit is None
            or selected_unit.army_slot != carrier.army_slot
            or selected_unit.unit_slot != carrier.unit_slot
            or selected_unit.unit_type != carrier.unit_type
        ):
            raise RuntimeError("Selected transport does not match the committed identity")
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
            or MenuItem.UNLOAD not in menu_state.ui.menu.items
        ):
            raise RuntimeError("The observed carrier action menu did not offer Drop")

        for drop_index, ((cargo, identity_id), drop) in enumerate(
            zip(linked_cargo, action.drops, strict=False)
        ):
            after_drop = await self.navigator.choose_unload(
                (drop.destination.x, drop.destination.y),
                unit=expected,
                width=battle.map.width,
                height=battle.map.height,
            )
            final_battle = after_drop.battle.value
            dropped = (
                next(
                    (item for item in final_battle.units if item.reference == cargo.reference), None
                )
                if final_battle is not None
                else None
            )
            live_carrier = (
                next(
                    (item for item in final_battle.units if item.reference == carrier.reference),
                    None,
                )
                if final_battle is not None
                else None
            )
            remaining_cargo = carrier.cargo_references[drop_index + 1 :]
            menu_is_carrier = (
                after_drop.ui.menu.family is MenuFamily.UNIT_ACTION_CHOICES
                and after_drop.ui.menu.selected_unit is not None
                and (
                    after_drop.ui.menu.selected_unit.army_slot,
                    after_drop.ui.menu.selected_unit.unit_slot,
                    after_drop.ui.menu.selected_unit.unit_type,
                    after_drop.ui.menu.selected_unit.record_address,
                )
                == expected
            )
            menu_closed_after_final_drop = (
                after_drop.ui.menu.family is MenuFamily.MAP_INPUT
                and drop_index == len(action.drops) - 1
                and not remaining_cargo
            )
            if (
                after_drop.battle.status is not ValueStatus.AVAILABLE
                or final_battle is None
                or dropped is None
                or live_carrier is None
                or dropped.embarked
                or not dropped.used_this_turn
                or (dropped.x, dropped.y) != (drop.destination.x, drop.destination.y)
                or live_carrier.cargo_references != remaining_cargo
                or not (menu_is_carrier or menu_closed_after_final_drop)
            ):
                raise RuntimeError(
                    f"Drop did not produce the expected cargo state for {identity_id}"
                )

        final_state = (
            after_drop
            if after_drop.ui.menu.family is MenuFamily.MAP_INPUT
            else await self.navigator.choose_wait()
        )
        final_battle = final_state.battle.value
        final_carrier = (
            next((item for item in final_battle.units if item.reference == carrier.reference), None)
            if final_battle is not None
            else None
        )
        if (
            final_state.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
            or final_carrier is None
            or not final_carrier.used_this_turn
            or (final_carrier.x, final_carrier.y) != final_carrier_position
            or any(
                (
                    dropped := next(
                        (
                            item
                            for item in final_battle.units
                            if item.reference == cargo_unit.reference
                        ),
                        None,
                    )
                )
                is None
                or dropped.embarked
                or not dropped.used_this_turn
                or (dropped.x, dropped.y) != (drop.destination.x, drop.destination.y)
                for (cargo_unit, _), drop in zip(linked_cargo, action.drops, strict=False)
            )
            or final_carrier.cargo_references != carrier.cargo_references[len(action.drops) :]
        ):
            raise RuntimeError("Unload did not produce the expected final transport state")
        committed = self.tracker.commit_boundary(final_state)
        committed_ids = {unit.reference: unit.identity_id for unit in committed.unit_identities}
        if committed_ids.get(carrier.reference) != action.transport_id or any(
            committed_ids.get(cargo.reference) != identity_id
            for (cargo, identity_id) in linked_cargo[: len(action.drops)]
        ):
            self.tracker.mark_uncertain(
                "Unit identities changed while committing the Unload result"
            )
            raise RuntimeError("Unload changed a transport or cargo lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
