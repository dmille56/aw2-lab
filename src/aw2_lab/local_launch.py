"""One-use browser handoffs and a narrowly scoped local watch credential."""

from __future__ import annotations

import secrets
import time
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class LocalLaunch:
    def __init__(self, app: FastAPI, base_url: str, operator: str) -> None:
        self.base_url = base_url
        self.operator = operator
        self.watch_token = secrets.token_urlsafe(32)
        self.match_id: UUID | None = None
        self.tickets: dict[str, tuple[str, float]] = {}
        app.add_middleware(WatchAccess, launch=self)
        app.add_api_route("/local-launch/claim", self.claim, methods=["POST"])

    def browser_url(self, token: str) -> str:
        ticket = secrets.token_urlsafe(32)
        self.tickets[ticket] = (token, time.monotonic() + 300)
        # Fragments never enter HTTP access logs or Referer headers. The client
        # clears this one-use capability before exchanging it for credentials.
        return f"{self.base_url}/client/#launch={ticket}"

    async def claim(self, request: Request) -> JSONResponse:
        if request.headers.get("origin", self.base_url) != self.base_url:
            raise HTTPException(403, "Launch handoff requires the same origin")
        if len(await request.body()) > 4096:
            raise HTTPException(400, "Invalid launch handoff")
        try:
            body = await request.json()
            ticket = body.get("ticket") if isinstance(body, dict) else None
            if not isinstance(ticket, str):
                raise TypeError
        except ValueError, TypeError:
            raise HTTPException(400, "Invalid launch handoff") from None
        entry = self.tickets.pop(ticket, None)
        if entry is None or entry[1] < time.monotonic() or self.match_id is None:
            raise HTTPException(410, "Launch link expired or already used")
        return JSONResponse(
            {"match_id": str(self.match_id), "token": entry[0]},
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )


class WatchAccess:
    """Translate only explicit read operations for one match; reject all mutations."""

    def __init__(self, app: ASGIApp, launch: LocalLaunch) -> None:
        self.app = app
        self.launch = launch

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = list(scope["headers"])
            expected = f"Bearer {self.launch.watch_token}".encode()
            if any(
                k == b"authorization" and secrets.compare_digest(v, expected) for k, v in headers
            ):
                prefix = f"/v1/matches/{self.launch.match_id}"
                allowed = {
                    "/v1/capabilities",
                    *(
                        prefix + p
                        for p in (
                            "/identity",
                            "/state",
                            "/observation",
                            "/screenshot",
                            "/events",
                        )
                    ),
                }
                if (
                    scope["method"] != "GET"
                    or scope["path"] not in allowed
                    or self.launch.match_id is None
                ):
                    await JSONResponse({"detail": "Watch access is read only"}, status_code=403)(
                        scope, receive, send
                    )
                    return
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in headers if k != b"authorization"] + [
                    (b"authorization", f"Bearer {self.launch.operator}".encode()),
                ]
        await self.app(scope, receive, send)
