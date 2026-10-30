"""Controller-input executor for moving a capture unit and capturing a property."""

from __future__ import annotations

from dataclasses import dataclass

from aw2_lab.action_navigation import ActionNavigator, validate_path
from aw2_lab.lifecycle import LifecyclePhase
from aw2_lab.match_contract import (
    CommandRequest,
    ErrorCode,
    MatchLifecycle,
    MoveCaptureAction,
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

_CAPTURABLE_TERRAINS = frozenset({6, 8, 14})  # city, HQ, and base on the supported ROM
_CAPTURE_UNIT_TYPES = frozenset({1, 2})  # Infantry and Mech
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
class MoveCaptureActionExecutor:
    """Execute movement, Capture, and a verified post-capture outcome."""

    navigator: ActionNavigator
    tracker: MatchObservationTracker

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        action = request.action
        if not isinstance(action, MoveCaptureAction):
            raise CommandRejected(ErrorCode.UNSUPPORTED_FEATURE, "Only move_capture is supported")
        battle = observation.game_state.battle.value
        if (
            observation.action_readiness is not ActionReadiness.READY
            or observation.identity_status is not IdentityStatus.AVAILABLE
            or battle is None
            or observation.game_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Move and Capture requires a ready, identified player-turn observation",
            )
        identity = next(
            (unit for unit in observation.unit_identities if unit.identity_id == action.unit_id),
            None,
        )
        unit = next(
            (
                unit
                for unit in battle.units
                if identity is not None and unit.reference == identity.reference
            ),
            None,
        )
        if (
            identity is None
            or unit is None
            or unit.army_slot != battle.active_player_slot
            or unit.used_this_turn
        ):
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Capturing unit is unavailable")
        if unit.unit_type not in _CAPTURE_UNIT_TYPES:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST, "Only Infantry and Mechs can capture properties"
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
        prop = next((item for item in battle.properties if (item.x, item.y) == destination), None)
        if prop is None or prop.terrain_class not in _CAPTURABLE_TERRAINS:
            raise CommandRejected(
                ErrorCode.INVALID_REQUEST,
                "Capture destination is not a supported capturable property",
            )
        # The fixed public match maps slot 1 to Red (owner code 1) and slot 2 to
        # Blue (owner code 2), as established by the supported ROM profile.
        if prop.owner_slot == unit.army_slot:
            raise CommandRejected(ErrorCode.INVALID_REQUEST, "Property is already owned")

        # All caller-controlled rejection happens before the first emulator input.
        selected = await self.navigator.select_unit(action.unit_id, observation)
        selected_unit = selected.ui.menu.selected_unit
        if selected_unit is None:
            raise RuntimeError("Selected unit was not present in the movement overlay")
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
        final_state = await self.navigator.choose_capture()

        if final_state.lifecycle.phase in _TERMINAL_PHASES:
            committed = self.tracker.commit_terminal_boundary(final_state)
            return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.FINISHED)

        final_battle = final_state.battle.value
        if (
            final_state.lifecycle.phase is not LifecyclePhase.BATTLE_PLAYER_TURN
            or final_state.ui.menu.family is not MenuFamily.MAP_INPUT
            or final_state.battle.status is not ValueStatus.AVAILABLE
            or final_battle is None
        ):
            raise RuntimeError("Capture did not return to a recognized player-turn boundary")
        final_unit = next(
            (
                candidate
                for candidate in final_battle.units
                if candidate.reference == unit.reference
            ),
            None,
        )
        final_property = next(
            (item for item in final_battle.properties if (item.x, item.y) == destination), None
        )
        previous_progress = 0 if path else unit.capture_points
        captured = final_property is not None and final_property.owner_slot == unit.army_slot
        progressed = final_unit is not None and final_unit.capture_points > previous_progress
        if (
            final_unit is None
            or final_unit.unit_type != unit.unit_type
            or (final_unit.x, final_unit.y) != destination
            or not final_unit.used_this_turn
            or not (captured or progressed)
        ):
            raise RuntimeError("Capture did not produce verified progress or property ownership")

        committed = self.tracker.commit_boundary(final_state)
        committed_identity = next(
            (item for item in committed.unit_identities if item.reference == unit.reference), None
        )
        if committed_identity is None or committed_identity.identity_id != action.unit_id:
            self.tracker.mark_uncertain("Unit lifetime identity changed during Capture")
            raise RuntimeError("Capture changed the acting unit's lifetime identity")
        return MutationOutcome(observation=committed, lifecycle=MatchLifecycle.PLAYABLE)
