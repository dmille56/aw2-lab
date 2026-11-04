"""Session-owned, authorized invalidations for committed MCP resources."""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import anyio
from anyio.abc import TaskStatus
from mcp import McpError, types
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import NotificationOptions
from mcp.server.session import ServerSession
from pydantic import AnyUrl
from starlette.requests import Request

from aw2_lab.authorization import AuthorizationError, Permission
from aw2_lab.match_contract import MatchLifecycle
from aw2_lab.match_events import CommandUpdatedEvent
from aw2_lab.mcp_auth import MCPCaller, caller_from_request
from aw2_lab.mcp_runtime import MCPAdapterRuntime

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    scope: anyio.CancelScope | None = None


class MCPResourceNotifications:
    """Bound subscriptions by session; publisher buffers retain their existing bounds."""

    def __init__(self, adapter: MCPAdapterRuntime) -> None:
        self.adapter = adapter
        self.active: dict[tuple[ServerSession, str], Subscription] = {}

    async def subscribe(self, caller: MCPCaller, session: ServerSession, uri: AnyUrl) -> None:
        parts = str(uri).split("/")
        try:
            if parts[:4] != ["aw2:", "", "v1", "matches"]:
                raise ValueError
            match_id = UUID(parts[4])
            command_id = None
            if len(parts) == 6 and parts[5] == "state":
                pass
            elif len(parts) == 7 and parts[5] == "commands":
                command_id = UUID(parts[6])
            else:
                raise ValueError
        except ValueError, IndexError:
            raise McpError(
                types.ErrorData(code=types.INVALID_PARAMS, message="Unsupported resource URI")
            ) from None
        self.adapter._check(caller)
        caller.check(Permission.READ, match_id)
        key = (session, str(uri))
        if key in self.active:
            return
        if len(self.active) >= 64 or sum(s is session for s, _ in self.active) >= 16:
            raise McpError(
                types.ErrorData(code=types.INVALID_PARAMS, message="Subscription capacity exceeded")
            )
        matches = self.adapter.matches
        assert matches is not None
        if command_id is not None:
            await matches.command_status(caller.principal, match_id, command_id)
        source = await matches.subscribe_events(caller.principal, match_id)
        # Registration may yield at the controller publication lock.
        if key in self.active:
            source.close()
            return
        if len(self.active) >= 64 or sum(s is session for s, _ in self.active) >= 16:
            source.close()
            raise McpError(
                types.ErrorData(code=types.INVALID_PARAMS, message="Subscription capacity exceeded")
            )
        entry = Subscription()
        self.active[key] = entry

        async def forward(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            nonlocal source
            try:
                async with self.adapter.operation(caller):
                    with anyio.CancelScope() as scope:
                        entry.scope = scope
                        task_status.started()
                        while True:
                            try:
                                message = await source.next()
                            except TimeoutError:
                                continue
                            except StopAsyncIteration:
                                # Overflow loses invalidations, never authoritative state.
                                caller.check(Permission.READ, match_id)
                                with anyio.fail_after(5):
                                    await session.send_resource_updated(uri)
                                state = await matches.state(caller.principal, match_id)
                                if state.summary.lifecycle is MatchLifecycle.CLOSED:
                                    return
                                source.close()
                                source = await matches.subscribe_events(caller.principal, match_id)
                                continue
                            event = message.event
                            if command_id is not None and isinstance(event, CommandUpdatedEvent):
                                if event.payload.command_id != command_id:
                                    continue
                            elif (
                                command_id is not None
                                and event.event != "snapshot"
                                or command_id is None
                                and event.event == "command.updated"
                            ):
                                continue
                            caller.check(Permission.READ, match_id)
                            with anyio.fail_after(5):
                                await session.send_resource_updated(uri)
            except (
                AuthorizationError,
                anyio.BrokenResourceError,
                anyio.ClosedResourceError,
                TimeoutError,
            ):
                pass
            except Exception:  # noqa: BLE001 -- isolate failed delivery from other sessions
                logger.error("MCP resource notification stopped unexpectedly")
            finally:
                source.close()
                if self.active.get(key) is entry:
                    self.active.pop(key)

        try:
            # The pinned SDK owns this group for the session, including DELETE/idle expiry.
            await session._task_group.start(forward)
        except BaseException:
            source.close()
            self.active.pop(key, None)
            raise

    def unsubscribe(self, caller: MCPCaller, session: ServerSession, uri: AnyUrl) -> None:
        caller.check()
        entry = self.active.pop((session, str(uri)), None)
        if entry is not None and entry.scope is not None:
            entry.scope.cancel()


def register_notifications(server: FastMCP, adapter: MCPAdapterRuntime | None) -> None:
    if adapter is None:
        return
    notifications = MCPResourceNotifications(adapter)

    def context() -> tuple[MCPCaller, ServerSession]:
        context = server.get_context().request_context
        if not isinstance(context.request, Request):
            raise McpError(
                types.ErrorData(code=types.INVALID_PARAMS, message="Authentication required")
            )
        return caller_from_request(context.request), context.session

    async def subscribe(request: types.SubscribeRequest) -> types.ServerResult:
        caller, session = context()
        await notifications.subscribe(caller, session, request.params.uri)
        return types.ServerResult(types.EmptyResult())

    async def unsubscribe(request: types.UnsubscribeRequest) -> types.ServerResult:
        caller, session = context()
        notifications.unsubscribe(caller, session, request.params.uri)
        return types.ServerResult(types.EmptyResult())

    server._mcp_server.request_handlers[types.SubscribeRequest] = subscribe
    server._mcp_server.request_handlers[types.UnsubscribeRequest] = unsubscribe
    original_capabilities = server._mcp_server.get_capabilities

    def capabilities(
        notification_options: NotificationOptions,
        experimental_capabilities: dict[str, dict[str, Any]],
    ) -> types.ServerCapabilities:
        result = original_capabilities(notification_options, experimental_capabilities)
        if result.resources is not None:
            result.resources.subscribe = True
        return result

    # SDK 1.29 hardcodes subscribe=False even when subscribe handlers are registered.
    server._mcp_server.get_capabilities = capabilities  # type: ignore[method-assign]
