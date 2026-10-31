"""Controller-input executor for purchasing a unit from an owned base."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.aw2_unit_profiles import UNIT_PROFILES
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    ErrorCode,
    MatchLifecycle,
    PurchaseAction,
)
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.state_model import ValueStatus
from aw2_lab.ui_state import PRODUCTION_CHOICES, MenuFamily

_BASE_TERRAIN = 14
_PURCHASABLE_BASE_TYPES = frozenset(PRODUCTION_CHOICES)


def _normalize_unit_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


_UNIT_TYPE_BY_NAME = {
    _normalize_unit_name(profile.name): unit_type
    for unit_type, profile in UNIT_PROFILES.items()
    if unit_type in _PURCHASABLE_BASE_TYPES
}
_UNIT_TYPE_BY_NAME["mdtank"] = 3


@dataclass(slots=True)
class PurchaseActionExecutor:
    """Purchase one verified base unit and validate funds and its new record."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, PurchaseAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only purchase is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Purchase requires a ready, identified player-turn observation",
            )
        unit_type = _UNIT_TYPE_BY_NAME.get(_normalize_unit_name(action.unit_type))
        if unit_type is None:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Unit type is not available from the researched base production menu",
            )
        x, y = action.property.x, action.property.y
        if not (0 <= x < battle.map.width and 0 <= y < battle.map.height):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST, "Production property is outside the map"
            )
        prop = next((item for item in battle.properties if (item.x, item.y) == (x, y)), None)
        if prop is None or prop.terrain_class != _BASE_TERRAIN:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Purchase currently supports researched base production only",
            )
        if prop.owner_slot != battle.active_player_slot:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Production base is not owned by you")
        if any(not unit.embarked and (unit.x, unit.y) == (x, y) for unit in battle.units):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Production base is occupied")
        player = next(
            (item for item in battle.players if item.slot == battle.active_player_slot), None
        )
        cost = UNIT_PROFILES[unit_type].cost
        if player is None or player.funds < cost:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Insufficient funds for this unit")

        # Caller-controlled rejection is complete before the first controller input.
        await self.navigator.open_production_menu(x, y)
        final_state = await self.navigator.choose_purchase_unit(unit_type)
        final_battle = final_state.battle.value
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
        ):
            raise RuntimeError("Purchase did not return to a recognized player-turn boundary")
        final_player = next(
            (item for item in final_battle.players if item.slot == battle.active_player_slot), None
        )
        purchased = [
            unit
            for unit in final_battle.units
            if unit.army_slot == battle.active_player_slot
            and unit.unit_type == unit_type
            and (unit.x, unit.y) == (x, y)
            and unit.reference not in {old.reference for old in battle.units}
        ]
        if (
            final_player is None
            or final_player.funds != player.funds - cost
            or len(purchased) != 1
            or not purchased[0].used_this_turn
            or len(final_battle.units) != len(battle.units) + 1
        ):
            raise RuntimeError("Purchase did not match expected funds and new-unit postconditions")

        committed = self.tracker.commit_boundary(final_state)
        new_reference = purchased[0].reference
        new_identity = next(
            (item for item in committed.unit_identities if item.reference == new_reference), None
        )
        if new_identity is None or any(
            item.identity_id == new_identity.identity_id for item in observation.unit_identities
        ):
            self.tracker.mark_uncertain("Purchased unit did not receive a new lifetime identity")
            raise RuntimeError("Purchase failed to create a new unit lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
