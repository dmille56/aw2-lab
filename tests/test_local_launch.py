"""Browser handoffs grant one slot once; watch credentials cannot mutate games."""

import time
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from aw2_lab.local_launch import LocalLaunch


@pytest.mark.anyio
async def test_ticket_is_same_origin_one_use_and_not_cached():
    app = FastAPI()
    launch = LocalLaunch(app, "http://test", "operator" * 8)
    launch.match_id = uuid4()
    token = "player-token" * 4
    url = launch.browser_url(token)
    assert token not in url and "?" not in url
    ticket = url.split("#launch=")[1]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        blocked = await client.post(
            "/local-launch/claim", json={"ticket": ticket}, headers={"Origin": "http://evil"}
        )
        assert blocked.status_code == 403
        response = await client.post(
            "/local-launch/claim", json={"ticket": ticket}, headers={"Origin": "http://test"}
        )
        assert response.json() == {"match_id": str(launch.match_id), "token": token}
        assert response.headers["cache-control"] == "no-store"
        assert (
            await client.post("/local-launch/claim", json={"ticket": ticket})
        ).status_code == 410
        expired = launch.browser_url(token).split("#launch=")[1]
        launch.tickets[expired] = (token, time.monotonic() - 1)
        assert (
            await client.post("/local-launch/claim", json={"ticket": expired})
        ).status_code == 410
        for body in ({}, [], {"ticket": []}):
            assert (await client.post("/local-launch/claim", json=body)).status_code == 400


@pytest.mark.anyio
async def test_watch_access_is_confined_to_read_operations_of_one_match():
    app = FastAPI()
    seen = []

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def endpoint(request: Request):
        seen.append(request.headers.get("authorization"))
        return {"ok": True}

    launch = LocalLaunch(app, "http://test", "o" * 40)
    launch.match_id = uuid4()
    headers = {"Authorization": f"Bearer {launch.watch_token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test", headers=headers
    ) as client:
        for path in (
            "/v1/capabilities",
            *(
                f"/v1/matches/{launch.match_id}/{suffix}"
                for suffix in ("state", "events", "identity", "screenshot", "observation")
            ),
        ):
            assert (await client.get(path)).status_code == 200
            assert seen[-1] == "Bearer " + "o" * 40
        count = len(seen)
        for method, path in (
            ("POST", f"/v1/matches/{launch.match_id}/commands"),
            ("GET", "/v1/readiness"),
            ("GET", f"/v1/matches/{uuid4()}/state"),
            ("GET", "/v1/matches"),
            ("POST", "/mcp/"),
        ):
            assert (await client.request(method, path)).status_code == 403
        assert len(seen) == count
        await client.get("/health", headers={"Authorization": "Bearer unrelated"})
        assert seen[-1] == "Bearer unrelated"
