"""Guarded activation of researched normal and Super CO Powers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    ActivateNormalPowerAction,
    ActivateSuperPowerAction,
    CommandRequest,
    ErrorCode,
    GameplayAction,
    MatchLifecycle,
)
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.state_model import GameState, ValueStatus
from aw2_lab.state_validation import BattleLayout, load_battle_layout
from aw2_lab.ui_state import CursorStatus, MenuFamily, MenuItem

_PLAYER_SLOT_NUMBER = {"slot_1": 1, "slot_2": 2}
_VERIFIED_MAX_USE_COUNTER = 9
_COST_FUNCTION = Callable[[tuple[int, ...], int, int], int]


def _power_cost(stars_by_co: tuple[int, ...], co_id: int, use_counter: int, label: str) -> int:
    """Return a researched CO Power threshold in raw meter units."""
    if len(stars_by_co) != 19 or not 1 <= co_id <= 18:
        raise ValueError("CO power-star metadata is unavailable")
    if not 0 <= use_counter <= _VERIFIED_MAX_USE_COUNTER:
        raise ValueError("Power-use counter is outside the verified cost range")
    stars = stars_by_co[co_id]
    if not 1 <= stars <= 10:
        raise ValueError(f"CO {label} star count is unrecognized")
    next_counter = use_counter + 1
    return stars * (9000 * (100 + 20 * next_counter) // 100)


def normal_power_cost(co_power_stars: tuple[int, ...], co_id: int, use_counter: int) -> int:
    """Return this CO's next normal Power threshold in raw meter units."""
    return _power_cost(co_power_stars, co_id, use_counter, "normal Power")


def super_power_cost(co_super_power_stars: tuple[int, ...], co_id: int, use_counter: int) -> int:
    """Return this CO's next Super Power threshold in raw meter units."""
    return _power_cost(co_super_power_stars, co_id, use_counter, "Super Power")


@dataclass(slots=True)
class _ActivatePowerActionExecutor:
    """Shared guarded menu navigation and postcondition for one Power kind."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker
    rom_path: Path
    layout_loader: Callable[[Path], BattleLayout] | None = None

    action_type: ClassVar[type[GameplayAction]]
    menu_item: ClassVar[MenuItem]
    active_power_kind: ClassVar[int]
    star_attribute: ClassVar[str]
    power_label: ClassVar[str]
    cost_function: ClassVar[_COST_FUNCTION]

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        if not isinstance(request.action, self.action_type):
            raise CommandRejected(
                ErrorCode.UNSUPPORTED_FEATURE, f"Only {self.power_label} is supported"
            )

        game_state = observation.game_state
        battle = game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or battle is None
            or game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or game_state.ui.menu.family is not MenuFamily.MAP_INPUT
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                f"{self.power_label} requires a ready, settled player-turn boundary",
            )

        expected_player = _PLAYER_SLOT_NUMBER[request.player_slot.value]
        if battle.active_player_slot != expected_player:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "It is not your active turn")

        if battle.co_effects_enabled.status is not ValueStatus.AVAILABLE:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "CO Power rules are not known",
            )
        if not battle.co_effects_enabled.value:
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "CO Powers are disabled")

        player = next((item for item in battle.players if item.slot == expected_player), None)
        if player is None or not 1 <= player.co_id <= 18:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "The active player's CO identity is not recognized",
            )
        if player.active_power not in (0, 1, 2):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "The active Power state is not recognized",
            )
        if player.active_power != 0:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "A CO Power is already active")
        if (
            player.power_meter.status is not ValueStatus.AVAILABLE
            or player.power_meter.value is None
            or player.power_use_counter.status is not ValueStatus.AVAILABLE
            or player.power_use_counter.value is None
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "The active player's Power meter or use counter is unknown",
            )

        current_counter = player.power_use_counter.value
        if current_counter > _VERIFIED_MAX_USE_COUNTER:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "The next CO Power cost is outside the runtime-verified use-counter range",
            )

        try:
            layout = (self.layout_loader or load_battle_layout)(self.rom_path)
        except OSError, ValueError:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Verified CO Power cost metadata is unavailable",
            ) from None
        stars_by_co = getattr(layout, self.star_attribute)
        if layout.profile != game_state.context.rom_profile or len(stars_by_co) != 19:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "CO Power cost metadata does not match the observed ROM",
            )
        try:
            meter_cost = type(self).cost_function(stars_by_co, player.co_id, current_counter)
        except ValueError:
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                f"The active CO's {self.power_label} cost is not recognized",
            ) from None
        next_counter = current_counter + 1
        if player.power_meter.value < meter_cost:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Insufficient CO Power meter")

        # Verify the exact separate command row before confirming it.
        command_menu = await self.navigator.open_command_menu()
        if (
            command_menu.ui.menu.family is not MenuFamily.COMMAND
            or self.menu_item not in command_menu.ui.menu.items
            or command_menu.ui.menu.actionable is not True
        ):
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                f"{self.power_label} is not available in the active player's command menu",
            )
        selected = await self.navigator.navigate_menu(self.menu_item)
        if (
            selected.ui.menu.family is not MenuFamily.COMMAND
            or selected.ui.menu.selected_item is not self.menu_item
            or selected.ui.menu.actionable is not True
        ):
            raise RuntimeError(f"{self.power_label} was not selected in the command menu")

        def settled(value: GameState) -> bool:
            return (
                value.lifecycle.phase is LifecyclePhase.BATTLE_PLAYER_TURN
                and value.ui.menu.family is MenuFamily.MAP_INPUT
                and value.battle.status is ValueStatus.AVAILABLE
                and value.battle.value is not None
                and value.battle.value.active_player_slot == expected_player
            )

        final_state = await self.navigator.confirm(
            settled,
            label=self.power_label.lower().replace(" ", "-"),
            frame_budget=self.navigator.limits.resolution_frame_budget,
            poll_frames=self.navigator.limits.resolution_poll_frames,
            wall_timeout=self.navigator.limits.resolution_wall_timeout,
        )
        final_battle = final_state.battle.value
        final_player = (
            next((item for item in final_battle.players if item.slot == expected_player), None)
            if final_battle is not None
            else None
        )
        if (
            final_battle is None
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.ui.map_cursor.status is not CursorStatus.AVAILABLE
            or final_player is None
            or final_player.co_id != player.co_id
            or final_player.active_power != self.active_power_kind
            or final_player.power_meter.status is not ValueStatus.AVAILABLE
            or final_player.power_meter.value != player.power_meter.value - meter_cost
            or final_player.power_use_counter.status is not ValueStatus.AVAILABLE
            or final_player.power_use_counter.value != next_counter
        ):
            raise RuntimeError(
                f"{self.power_label} did not reach its verified settled postcondition"
            )

        committed = self.tracker.commit_boundary(final_state)
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)


@dataclass(slots=True)
class ActivateNormalPowerActionExecutor(_ActivatePowerActionExecutor):
    """Activate normal Power only when observed state and its CO cost are known."""

    action_type: ClassVar[type[GameplayAction]] = ActivateNormalPowerAction
    menu_item: ClassVar[MenuItem] = MenuItem.POWER
    active_power_kind: ClassVar[int] = 1
    star_attribute: ClassVar[str] = "co_power_stars"
    power_label: ClassVar[str] = "Normal Power"
    cost_function: ClassVar[_COST_FUNCTION] = normal_power_cost


@dataclass(slots=True)
class ActivateSuperPowerActionExecutor(_ActivatePowerActionExecutor):
    """Activate Super Power only when observed state and its CO cost are known."""

    action_type: ClassVar[type[GameplayAction]] = ActivateSuperPowerAction
    menu_item: ClassVar[MenuItem] = MenuItem.SUPER_POWER
    active_power_kind: ClassVar[int] = 2
    star_attribute: ClassVar[str] = "co_super_power_stars"
    power_label: ClassVar[str] = "Super Power"
    cost_function: ClassVar[_COST_FUNCTION] = super_power_cost
