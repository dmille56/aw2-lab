"""Synthetic HTTP/SSE fixture for browser/native checks; never starts an emulator."""

import argparse
import asyncio
import base64
import importlib.util
import os
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from aw2_lab.api_contract import CapabilitiesResponse, FeatureAvailability, StateResponse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("client_serve", ROOT / "serve.py")
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
app = FastAPI()
helper.configure_client(app)
template: dict[str, Any] = StateResponse.model_validate_json(
    (ROOT / "tests/fixtures/state.json").read_text()
).model_dump(mode="json")
state = deepcopy(template)
revoked = False
mismatch = False
connections = 0
watchers: set[asyncio.Queue[str | None]] = set()
TOKEN = "synthetic-player-token"


def available(name: str) -> FeatureAvailability:
    return FeatureAvailability(
        name=name,
        implemented=True,
        available=True,
        verification="synthetic",
    )


capabilities = CapabilitiesResponse(
    operations=(available("state"), available("events")),
    http_sse=available("http_sse"),
    mcp_subscriptions=available("mcp_subscriptions"),
).model_dump(mode="json")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aKd8AAAAASUVORK5CYII="
)


def authorize(request: Request, mid: str) -> None:
    if (
        revoked
        or request.headers.get("Authorization") != f"Bearer {TOKEN}"
        or mid != state["summary"]["match_id"]
    ):
        raise HTTPException(403)


@app.get("/health")
async def health() -> dict[str, str | None]:
    return {
        "status": "ok",
        "emulator": "synthetic",
        "fixture_id": os.environ.get("AW2_CLIENT_FIXTURE_ID"),
    }


@app.get("/v1/capabilities")
async def get_capabilities() -> dict[str, Any]:
    return capabilities


@app.post("/__test/reset")
async def reset() -> dict[str, Any]:
    global state, revoked, mismatch, connections
    for queue in tuple(watchers):
        queue.put_nowait(None)
    state = deepcopy(template)
    revoked = mismatch = False
    connections = 0
    return state


@app.post("/__test/advance")
async def advance(disconnect: bool = False) -> dict[str, Any]:
    state["summary"]["revision"] += 1
    state["observation"]["revision"] += 1
    state["observation"]["game_state"]["frame"] += 1
    state["observation"]["game_state"]["battle"]["value"]["day"] += 1
    for queue in tuple(watchers):
        queue.put_nowait(None if disconnect else "match.updated")
    return state


@app.post("/__test/revoke")
async def revoke() -> dict[str, object]:
    global revoked
    revoked = True
    for queue in tuple(watchers):
        queue.put_nowait(None)
    return {}


@app.post("/__test/screenshot-mismatch")
async def screenshot_mismatch(enabled: bool = True) -> dict[str, object]:
    global mismatch
    mismatch = enabled
    return {}


@app.post("/__test/corrupt-state")
async def corrupt_state() -> dict[str, object]:
    state["contract_version"] = 999
    return {}


@app.get("/__test/stats")
async def stats() -> dict[str, int]:
    return {"connections": connections, "watchers": len(watchers)}


@app.get("/v1/matches/{mid}/identity")
async def identity(mid: str, request: Request) -> dict[str, object]:
    authorize(request, mid)
    return {"contract_version": 1, "match_id": mid, "role": "player", "player_slot": "slot_1"}


@app.get("/v1/matches/{mid}/state")
async def current(mid: str, request: Request) -> dict[str, Any]:
    authorize(request, mid)
    return state


@app.get("/v1/matches/{mid}/events")
async def events(mid: str, request: Request) -> StreamingResponse:
    global connections
    authorize(request, mid)
    connections += 1
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    watchers.add(queue)

    async def stream() -> AsyncIterator[str]:
        try:
            yield "event: snapshot\ndata: {}\n\n"
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield f"event: {event}\ndata: {{}}\n\n"
        finally:
            watchers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/v1/matches/{mid}/screenshot")
async def screenshot(mid: str, request: Request, revision: int) -> Response:
    authorize(request, mid)
    if revision != state["summary"]["revision"]:
        raise HTTPException(409)
    return Response(
        PNG,
        media_type="image/png",
        headers={
            "X-AW2-Match-ID": mid,
            "X-AW2-Revision": str(revision + 1 if mismatch else revision),
            "X-AW2-Frame": str(state["observation"]["game_state"]["frame"]),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=43979)
    parser.add_argument("--fd", type=int, help="serve on an already-bound socket descriptor")
    args = parser.parse_args()
    if args.fd is None:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    else:
        uvicorn.run(app, fd=args.fd, log_level="warning")
