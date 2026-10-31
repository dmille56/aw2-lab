"""Execute End Turn and verify the next playable turn or match result."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, EndTurnAction, ErrorCode, MatchLifecycle
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.state_model import ValueStatus
from aw2_lab.ui_state import MenuFamily, MenuItem

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
class EndTurnActionExecutor:
    """End the active player's turn, recording actual post-upkeep state."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        if not isinstance(request.action, EndTurnAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only end_turn is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "End Turn requires a ready, identified player-turn observation",
            )

        await self.navigator.open_command_menu()
        await self.navigator.navigate_menu(MenuItem.END)
        final_state = await self.navigator.confirm_end_turn()
        if final_state.lifecycle.phase in _TERMINAL_PHASES:
            committed = self.tracker.commit_terminal_boundary(final_state)
            return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.FINISHED)

        next_battle = final_state.battle.value
        expected_player = 2 if battle.active_player_slot == 1 else 1
        expected_day = battle.day + (1 if battle.active_player_slot == 2 else 0)
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or next_battle is None
            or next_battle.active_player_slot != expected_player
            or next_battle.day != expected_day
            or not any(player.slot == expected_player for player in next_battle.players)
        ):
            raise RuntimeError("End Turn did not reach the expected next player/day boundary")
        if any(
            unit.used_this_turn for unit in next_battle.units if unit.army_slot == expected_player
        ):
            raise RuntimeError("Next player's units were not reset at turn start")

        committed = self.tracker.commit_boundary(final_state)
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
