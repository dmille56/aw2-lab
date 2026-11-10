"""One emulator/session owner for queued startup, gameplay, checkpoints, and rollback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal
from uuid import UUID

from aw2_lab.action_navigation import ActionNavigator
from aw2_lab.api_contract import configuration_from_controller
from aw2_lab.api_validation import validate_configuration
from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.checkpoint_store import CheckpointStore
from aw2_lab.cold_boot import ColdBootResult, boot_fixed_versus_match
from aw2_lab.command_journal import JsonlCommandJournal
from aw2_lab.end_turn_executor import EndTurnActionExecutor
from aw2_lab.match_checkpoint import CheckpointRuntime, CheckpointSession, MatchCheckpointService
from aw2_lab.match_contract import (
    ActivateNormalPowerAction,
    CommandRequest,
    ErrorBody,
    ErrorCode,
    MatchLifecycle,
)
from aw2_lab.match_controller import (
    ActionExecutor,
    CommandRejected,
    MatchController,
    MutationOutcome,
)
from aw2_lab.match_observation import ActionReadiness, MatchObservation, MatchObservationTracker
from aw2_lab.move_attack_executor import MoveAttackActionExecutor
from aw2_lab.move_capture_executor import MoveCaptureActionExecutor
from aw2_lab.move_wait_executor import MoveWaitActionExecutor
from aw2_lab.purchase_executor import PurchaseActionExecutor
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.state_model import GameState
from aw2_lab.surrender_executor import SurrenderActionExecutor
from aw2_lab.transport_executor import LoadActionExecutor, UnloadActionExecutor

BootMatch = Callable[..., Awaitable[ColdBootResult]]


class PlayableRuntime:
    """Resolve the current session tracker at execution, including after restore."""

    def __init__(
        self,
        *,
        controller: MatchController,
        bridge: LuaBridgeClient,
        rom_path: Path,
        rom_sha256: str,
        emulator_build: str,
        emulator_mode: Literal["headless", "windowed"],
        store: CheckpointStore,
        journal: JsonlCommandJournal,
        recovered_service: MatchCheckpointService | None = None,
        boot_match: BootMatch = boot_fixed_versus_match,
        observe: Callable[[], Awaitable[GameState]] | None = None,
        session_changed: Callable[[MatchCheckpointService], None] | None = None,
    ) -> None:
        self.controller = controller
        self.bridge = bridge
        self.rom_path = rom_path
        self.store = store
        self.journal = journal
        self.identity = CheckpointRuntime(rom_sha256, emulator_build, emulator_mode)
        self._service = recovered_service
        self._session_changed = session_changed
        self._boot_match = boot_match
        self._observe = observe or self._capture
        self.navigator = ActionNavigator(
            bridge,
            self._observe,
            screenshot_writer=self._save_navigation_screenshot,
            screenshot_directory=store.root / "navigation-failures",
        )
        controller.configure_runtime(self, self.start)
        controller.set_screenshot_provider(self.capture_screenshot)
        # These delegates remain installed as match/session ownership changes.
        controller.set_recovery_checkpoint_provider(self.capture_recovery, replace=True)
        controller.set_recovery_rollback_provider(self.rollback, replace=True)
        controller.set_input_release_provider(self.release_inputs, replace=True)

    async def _capture(self) -> GameState:
        return await capture_game_state(self.bridge, rom_path=self.rom_path)

    async def _save_navigation_screenshot(self, path: Path) -> Path:
        return await self.bridge.save_screenshot(path)

    async def capture_screenshot(self, observation: MatchObservation) -> bytes:
        """Capture only while the bridge remains on the committed observation frame."""
        before = await self.bridge.read_memory_snapshot([(0x03000000, 1)])
        if before.frame != observation.game_state.frame:
            raise RuntimeError("Screenshot frame differs from the observed boundary")
        png = await self.bridge.screenshot()
        after = await self.bridge.read_memory_snapshot([(0x03000000, 1)])
        if after.frame != before.frame:
            raise RuntimeError("Emulator advanced while capturing its boundary screenshot")
        return png

    @property
    def checkpoints(self) -> MatchCheckpointService:
        if self._service is None:
            raise CommandRejected(ErrorCode.RUNTIME_UNAVAILABLE, "No initialized runtime session")
        return self._service

    async def start(self, match_id: UUID) -> MutationOutcome:
        summary = await self.controller.inspect_match(match_id)
        validate_configuration(configuration_from_controller(summary.configuration))
        # Failure after this point is a recovery-required start, never a playable publication.
        await self.release_inputs()
        await self.bridge.reset()
        self._service = MatchCheckpointService(
            controller=self.controller,
            store=self.store,
            bridge=self.bridge,
            session=CheckpointSession(MatchObservationTracker(match_id), self._observe),
            runtime=self.identity,
            journal=self.journal,
        )
        if self._session_changed is not None:
            self._session_changed(self._service)
        # Existing-save confirmations are restricted to the isolated emulator save copy.
        result = await self._boot_match(self.bridge, rom_path=self.rom_path, save_mode="existing")
        observation = self.checkpoints.session.tracker.commit_boundary(result.game_state)
        if observation.action_readiness is not ActionReadiness.READY:
            raise RuntimeError("Startup did not reach a recognized playable boundary")
        return await self.checkpoints.prepare_boundary_checkpoint(
            observation, MatchLifecycle.PLAYABLE
        )

    async def execute(
        self, request: CommandRequest, observation: MatchObservation
    ) -> MutationOutcome:
        service = self.checkpoints
        if (
            service.session.tracker.match_id != request.match_id
            or service.session.tracker.read() != observation
        ):
            raise CommandRejected(
                ErrorCode.OBSERVATION_UNAVAILABLE,
                "Runtime session does not match the committed state",
            )
        if isinstance(request.action, ActivateNormalPowerAction):
            raise CommandRejected(
                ErrorCode.UNSUPPORTED_FEATURE,
                "Normal CO Power execution is not implemented yet",
            )
        # Restores replace session.tracker. Never retain it in long-lived executors.
        executors: dict[
            str, Callable[[ActionNavigator, MatchObservationTracker], ActionExecutor]
        ] = {
            "move_wait": MoveWaitActionExecutor,
            "move_attack": MoveAttackActionExecutor,
            "attack": MoveAttackActionExecutor,
            "move_capture": MoveCaptureActionExecutor,
            "load": LoadActionExecutor,
            "unload": UnloadActionExecutor,
            "purchase": PurchaseActionExecutor,
            "end_turn": EndTurnActionExecutor,
            "surrender": SurrenderActionExecutor,
        }
        executor = executors[request.action.kind](self.navigator, service.session.tracker)
        outcome = await executor.execute(request, observation)
        if outcome.observation is None or outcome.lifecycle not in {
            MatchLifecycle.PLAYABLE,
            MatchLifecycle.FINISHED,
        }:
            raise RuntimeError("Gameplay executor did not produce a settled boundary")
        return await service.prepare_boundary_checkpoint(outcome.observation, outcome.lifecycle)

    async def capture_recovery(
        self, match_id: UUID, command_id: UUID, expected_revision: int | None
    ) -> UUID:
        return await self.checkpoints.capture_recovery_checkpoint(
            match_id, command_id, expected_revision
        )

    async def rollback(
        self, match_id: UUID, command_id: UUID, checkpoint_id: UUID, error: ErrorBody
    ) -> MutationOutcome:
        return await self.checkpoints.restore_recovery_checkpoint(
            match_id, command_id, checkpoint_id, error
        )

    async def release_inputs(self) -> None:
        if await self.bridge.set_keys(0) != 0:
            raise RuntimeError("Emulator did not release held inputs")
