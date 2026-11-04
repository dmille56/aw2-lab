"""Local MCP transport authentication and reusable per-operation access checks."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import TYPE_CHECKING
from uuid import UUID

import anyio
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from starlette.authentication import AuthCredentials
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aw2_lab.api_contract import Principal
from aw2_lab.authorization import AuthorizationError, AuthorizationService, Permission
from aw2_lab.match_contract import ErrorCode

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True)
class MCPCaller:
    """Captured identity is rechecked before reads, cached results, and delivery."""

    authorization: AuthorizationService = field(repr=False)
    principal: Principal
    credential: SecretStr = field(repr=False)

    def check(self, permission: Permission = Permission.READ, match_id: UUID | None = None) -> None:
        self.authorization.authorize(
            self.principal,
            permission,
            match_id if match_id is not None else getattr(self.principal, "match_id", None),
        )

    @asynccontextmanager
    async def operation(
        self, permission: Permission = Permission.READ, match_id: UUID | None = None
    ) -> AsyncIterator[None]:
        """Guard awaits/cached results; revocation wakes pending adapter work."""
        self.check(permission, match_id)
        loop = asyncio.get_running_loop()
        with anyio.CancelScope() as cancelled:

            def revoke() -> None:
                loop.call_soon_threadsafe(cancelled.cancel)

            unwatch = self.authorization.watch(self.principal, revoke)
            try:
                yield
            finally:
                unwatch()
        self.check(permission, match_id)


def caller_from_request(request: Request) -> MCPCaller:
    caller = request.scope.get("aw2.mcp_caller")
    if not isinstance(caller, MCPCaller):
        raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
    caller.check()
    return caller


class MCPAuthorizationBoundary:
    """Protect initialization, every session request, and each response delivery.

    The SDK uses AuthenticatedUser to bind sessions to the supplied client/subject
    identity. No session ID authenticates a caller. Revocation cancels an active
    transport request, without cancelling accepted controller commands.
    """

    def __init__(self, app: ASGIApp, authorization: AuthorizationService | None) -> None:
        self.app = app
        self.authorization = authorization

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        # Local provisioning only. Host/origin validation is also enforced by the SDK.
        peer = scope.get("client")
        try:
            local = peer is not None and ip_address(peer[0]).is_loopback
        except ValueError:
            local = False
        if not local:
            await self._error(scope, receive, send, 403, "Remote MCP access is disabled")
            return
        if self.authorization is None:
            await self._error(scope, receive, send, 503, "Operator provisioning is required")
            return
        headers = request.headers.getlist("authorization")
        try:
            if len(headers) != 1:
                raise ValueError
            scheme, raw = headers[0].split(" ", 1)
            if (
                scheme.lower() != "bearer"
                or not 32 <= len(raw) <= 128
                or any(c.isspace() for c in raw)
            ):
                raise ValueError
            secret = SecretStr(raw)
            principal = self.authorization.authenticate(secret)
            caller = MCPCaller(self.authorization, principal, secret)
            caller.check()
        except AuthorizationError, ValueError:
            await self._error(scope, receive, send, 401, "Authentication required")
            return
        # Distinct credentials and ledger generations cannot take over old sessions.
        identity = hashlib.sha256((raw + ":" + principal.model_dump_json()).encode()).hexdigest()
        scope["user"] = AuthenticatedUser(
            AccessToken(token=raw, client_id=identity, subject=identity, scopes=[])
        )
        scope["auth"] = AuthCredentials([])
        scope["aw2.mcp_caller"] = caller
        started = False
        finished = False
        denied = False
        loop = asyncio.get_running_loop()
        with anyio.CancelScope() as cancelled:

            def revoke() -> None:
                loop.call_soon_threadsafe(cancelled.cancel)

            unwatch = self.authorization.watch(principal, revoke)
            try:

                async def checked_send(message: Message) -> None:
                    nonlocal started, finished
                    caller.check()
                    if message["type"] == "http.response.start":
                        started = True
                        message = dict(message)
                        message["headers"] = [
                            *message.get("headers", []),
                            (b"cache-control", b"no-store"),
                        ]
                    if message["type"] == "http.response.body" and not message.get(
                        "more_body", False
                    ):
                        finished = True
                    await send(message)

                await self.app(scope, receive, checked_send)
            except AuthorizationError:
                denied = True
                if not started:
                    await self._error(scope, receive, send, 401, "Authentication required")
            finally:
                unwatch()
        if (cancelled.cancel_called or denied) and started and not finished:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        if cancelled.cancel_called and not started:
            await self._error(scope, receive, send, 401, "Authentication required")

    @staticmethod
    async def _error(scope: Scope, receive: Receive, send: Send, status: int, message: str) -> None:
        headers = {"Cache-Control": "no-store"}
        if status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        await JSONResponse({"error": message}, status_code=status, headers=headers)(
            scope, receive, send
        )
