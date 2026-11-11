"""Bounded MCP turn waits driven by the authoritative match publisher."""

import asyncio
from typing import Literal
from uuid import UUID

from aw2_lab.api_contract import PlayerPrincipal, StateResponse
from aw2_lab.authorization import AuthorizationError, Permission
from aw2_lab.match_contract import ContractModel, ErrorCode, MatchLifecycle, PlayerSlot
from aw2_lab.match_events import CommandUpdatedEvent
from aw2_lab.match_observation import ActionReadiness, IdentityStatus
from aw2_lab.mcp_auth import MCPCaller
from aw2_lab.mcp_runtime import MCPAdapterRuntime
from aw2_lab.sdk import AsyncAW2Client

TurnReason = Literal["turn_ready", "finished", "closed", "recovery_required", "timed_out"]


class TurnWaitResult(ContractModel):
    timed_out: bool
    reason: TurnReason
    state: StateResponse


def turn_reason(state: StateResponse, slot: PlayerSlot, after_revision: int) -> TurnReason | None:
    lifecycle = state.summary.lifecycle
    if lifecycle is MatchLifecycle.FINISHED:
        return "finished"
    if lifecycle is MatchLifecycle.CLOSED:
        return "closed"
    if lifecycle is MatchLifecycle.RECOVERY_REQUIRED:
        return "recovery_required"
    observation = state.observation
    battle = observation.game_state.battle.value if observation else None
    if (
        state.settled
        and lifecycle is MatchLifecycle.PLAYABLE
        and state.summary.revision > after_revision
        and observation is not None
        and observation.identity_status is IdentityStatus.AVAILABLE
        and observation.action_readiness is ActionReadiness.READY
        and battle is not None
        and battle.active_player_slot == (list(PlayerSlot).index(slot) + 1)
    ):
        return "turn_ready"
    return None


async def wait_for_turn(
    adapter: MCPAdapterRuntime,
    caller: MCPCaller,
    sdk: AsyncAW2Client,
    match_id: UUID,
    player_slot: PlayerSlot,
    after_revision: int,
    timeout_seconds: float,
) -> TurnWaitResult:
    """Called inside the tool's bounded, caller-owned SDK operation scope."""
    caller.check(Permission.READ, match_id)
    if (
        isinstance(caller.principal, PlayerPrincipal)
        and caller.principal.player_slot is not player_slot
    ):
        raise AuthorizationError(
            ErrorCode.PERMISSION_DENIED, "Players may wait only for their own slot"
        )
    matches = adapter.matches
    if matches is None:
        raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
    source = None
    try:
        async with asyncio.timeout(timeout_seconds):
            try:
                # Reserve the last 10% for an authorized final state read.
                async with asyncio.timeout(timeout_seconds * 0.9):
                    source = await matches.subscribe_events(caller.principal, match_id)
                    while True:
                        # Register before reading HTTP state: updates during the read remain buffered.
                        state = await sdk.state(match_id)
                        caller.check(Permission.READ, match_id)
                        reason = turn_reason(state, player_slot, after_revision)
                        if reason is not None:
                            return TurnWaitResult(timed_out=False, reason=reason, state=state)
                        while True:
                            try:
                                event = (await source.next(timeout=timeout_seconds)).event
                            except StopAsyncIteration:
                                # A bounded buffer overflow requires a fresh atomic snapshot.
                                source.close()
                                source = await matches.subscribe_events(caller.principal, match_id)
                                break
                            if not isinstance(event, CommandUpdatedEvent):
                                break
            except TimeoutError:
                state = await sdk.state(match_id)
                caller.check(Permission.READ, match_id)
                reason = turn_reason(state, player_slot, after_revision)
                return TurnWaitResult(
                    timed_out=reason is None, reason=reason or "timed_out", state=state
                )
    finally:
        if source is not None:
            source.close()
