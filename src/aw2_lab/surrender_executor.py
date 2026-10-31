"""Execute the researched Options > Yield > Yes surrender flow."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import CommandRequest, ErrorCode, MatchLifecycle, SurrenderAction
from aw2_lab.match_controller import CommandRejected, MutationOutcome
from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservation,
    MatchObservationTracker,
)
from aw2_lab.ui_state import MenuItem


@dataclass(slots=True)
class SurrenderActionExecutor:
    """Confirm surrender and publish only a recognized result boundary."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        if not isinstance(request.action, SurrenderAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only surrender is supported")
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or observation.game_state.battle.value is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Surrender requires a ready, identified player-turn observation",
            )

        await self.navigator.open_command_menu()
        await self.navigator.navigate_menu(MenuItem.YIELD)
        await self.navigator.open_yield_confirmation()
        result = await self.navigator.confirm_yield()
        terminal = self.tracker.commit_terminal_boundary(result)
        return MutationOutcome(observation=terminal, lifecycle=MatchLifecycle.FINISHED)
