"""Application-owned MCP SDK connections and pending operation lifetimes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager

import anyio
import httpx

from aw2_lab.authorization import AuthorizationError
from aw2_lab.authorized_match import AuthorizedMatchService
from aw2_lab.match_contract import ErrorCode
from aw2_lab.match_controller import MatchController
from aw2_lab.mcp_auth import MCPCaller
from aw2_lab.sdk import AsyncAW2Client


def api_url_for_bind(host: str, port: int) -> str:
    """Use a connectable local address when the listener binds all interfaces."""
    if not 1 <= port <= 65535:
        raise ValueError("MCP SDK connections require a fixed API port between 1 and 65535")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    return str(httpx.URL(scheme="http", host=host, port=port))


class MCPAdapterRuntime:
    """Lease caller work against the existing services; own no emulator or state."""

    def __init__(
        self,
        controller: MatchController,
        matches: Callable[[], AuthorizedMatchService | None],
        *,
        api_base_url: str,
        cleanup_timeout: float = 5,
    ) -> None:
        url = httpx.URL(api_base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("MCP requires the configured API origin without credentials or a path")
        if cleanup_timeout <= 0:
            raise ValueError("MCP cleanup timeout must be positive")
        self.controller = controller
        self.events = controller.events
        self._matches = matches
        self.api_base_url = str(url)
        self.cleanup_timeout = cleanup_timeout
        self.running = False
        self._started = False
        self._cleanup_failed = False
        self._active: set[anyio.CancelScope] = set()
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def matches(self) -> AuthorizedMatchService | None:
        return self._matches()

    def _check(self, caller: MCPCaller) -> None:
        if not self.running:
            raise AuthorizationError(ErrorCode.RUNTIME_UNAVAILABLE, "MCP adapter is unavailable")
        if self.matches is None or caller.authorization is not self.matches.authorization:
            raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid MCP caller")
        caller.check()

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        if self._started:
            raise RuntimeError("MCP adapter lifespan can only run once")
        self._started = True
        self.running = True
        try:
            yield
        finally:
            self.running = False
            for scope in tuple(self._active):
                scope.cancel()
            try:
                with anyio.fail_after(self.cleanup_timeout, shield=True):
                    await self._idle.wait()
            except TimeoutError:
                raise RuntimeError("MCP adapter cleanup deadline expired") from None
            if self._cleanup_failed:
                raise RuntimeError("MCP operation cleanup deadline expired")

    @asynccontextmanager
    async def operation(self, caller: MCPCaller) -> AsyncIterator[AsyncExitStack]:
        """Own waits/subscription cleanup callbacks as well as caller revocation."""
        self._check(caller)
        with anyio.CancelScope() as scope:
            self._active.add(scope)
            self._idle.clear()
            try:
                async with caller.operation():
                    stack = AsyncExitStack()
                    try:
                        yield stack
                        self._check(caller)
                    finally:
                        try:
                            with anyio.fail_after(self.cleanup_timeout, shield=True):
                                await stack.aclose()
                        except TimeoutError:
                            self._cleanup_failed = True
                            raise RuntimeError("MCP operation cleanup deadline expired") from None
            finally:
                self._active.remove(scope)
                if not self._active:
                    self._idle.set()
        self._check(caller)

    @asynccontextmanager
    async def sdk(self, caller: MCPCaller) -> AsyncIterator[AsyncAW2Client]:
        """The URL is application configuration; credentials belong to this caller."""
        async with self.operation(caller) as stack:
            client = AsyncAW2Client(self.api_base_url, credential=caller.credential)
            stack.push_async_callback(client.aclose)
            yield client
