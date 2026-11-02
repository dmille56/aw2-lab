# HTTP API v1

The implemented lifecycle and read routes use the shared authorization service
and match controller. `/health` retains its existing public payload. The public
`GET /v1/capabilities` describes the verified configuration, implemented routes,
runtime availability, production units, and limits. Gameplay submission,
checkpoints, readiness, SSE, debug routes, and MCP gameplay remain planned;
capabilities report those HTTP operations unavailable.

Start the normal server with your local ROM and the operator file described in
[AUTHORIZATION.md](AUTHORIZATION.md). With no operator file configured, match
routes return `503 runtime_unavailable`. Use the default loopback address
`http://127.0.0.1:43127`. Browser cross-origin access is disabled by default.

JSON payloads carry `contract_version: 1` (omission defaults to 1). Request models
and the error envelope are published in `/openapi.json` and `/docs`. Ordinary
JSON bodies are limited to 65,536 bytes; mutating routes require
`Content-Type: application/json`. Secrets belong in bearer headers or the
invitation request fields, and never in URLs.

| Route | Permission | Success |
| --- | --- | --- |
| `GET /v1/capabilities` | Public | 200, capabilities |
| `POST /v1/matches` | Operator | 201, summary and `Location` |
| `GET /v1/matches` | Operator | 200, match list |
| `GET /v1/matches/{match}` | Operator or that match's player | 200, summary |
| `POST /v1/matches/{match}/slots/{slot}/invitations` | Operator | 201, invitation reference |
| `POST /v1/matches/{match}/slots/{slot}/join` | New player bearer plus invitation | 200, join response |
| `POST /v1/matches/{match}/slots/{slot}/revoke` | Operator | 200, slot authorization |
| `POST /v1/matches/{match}/start` | Operator | 202, command receipt |
| `POST /v1/matches/{match}/close` | Operator | 202, command receipt |
| `GET /v1/matches/{match}/state` | Operator or that match's player | 200, coherent state |
| `GET /v1/matches/{match}/observation` | Operator or that match's player | 200, `{contract_version, observation}` |
| `GET /v1/matches/{match}/screenshot` | Operator or that match's player | 200, PNG |
| `GET /v1/matches/{match}/commands/{command}` | Operator or that match's player | 200, command result |

Both player slots can inspect their own match during either turn. Closing keeps
their retained read access; revocation invalidates it immediately, including
cached screenshots and command results. Operator credentials cannot play a slot.

Creation accepts an omitted configuration or the complete verified profile from
capabilities. Preserve `request_id` and the exact request when retrying a lost
response. Creating, issuing invitations, joining, revoking, and closing use the
shared durable retry semantics. Start requires both slots to be claimed and
`{request_id, expected_revision}`; close uses `{request_id}`. A `202` receipt means
accepted work: read its command-status route to learn completion or rejection.

For example, this trusted operator client creates and claims both setup slots
without printing credentials:

```python
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import httpx

operator_token = Path("~/.config/aw2-lab/operator-token").expanduser().read_text().strip()
with httpx.Client(
    base_url="http://127.0.0.1:43127",
    headers={"Authorization": f"Bearer {operator_token}"},
) as operator:
    response = operator.post("/v1/matches", json={"request_id": str(uuid4())})
    response.raise_for_status()
    match = response.json()["match_id"]
    player_tokens = {}
    for slot in ("slot_1", "slot_2"):
        invitation, credential = token_urlsafe(32), token_urlsafe(32)
        slot_url = f"/v1/matches/{match}/slots/{slot}"
        operator.post(slot_url + "/invitations", json={
            "request_id": str(uuid4()), "invitation_token": invitation,
        }).raise_for_status()
        operator.post(slot_url + "/join", headers={
            "Authorization": f"Bearer {credential}",
        }, json={
            "request_id": str(uuid4()), "display_name": slot,
            "invitation_token": invitation,
        }).raise_for_status()
        player_tokens[slot] = credential
    response = operator.post(f"/v1/matches/{match}/start", json={
        "request_id": str(uuid4()), "expected_revision": 0,
    })
    response.raise_for_status()
    command_id = response.json()["command_id"]
    result = operator.get(f"/v1/matches/{match}/commands/{command_id}")
    result.raise_for_status()  # Inspect status; the command may still be queued/running.
```

In separate player applications, distribute each invitation privately and let
each player generate its own credential before joining. The combined example is
for a trusted operator process; clients that only play do not receive its token.

State reads return the last committed observation even while a command is
executing; `settled` is then false. Before Start, observation is null. The
settled-only observation route returns `409 observation_unavailable` before
Start or during execution. Reads never advance emulator frames.

Screenshots are captured at boundary publication, checked against the observed
frame, and cached with the observation. During execution the route serves the
previous committed image. `X-AW2-Match-ID`, `X-AW2-Revision`, and `X-AW2-Frame`
identify it. Optional `?revision=N` requires that exact latest cached revision;
there is no historical-image endpoint. A capture failure clears the new image
and returns `409 observation_unavailable`, without discarding the game state.
Startup restores regenerate the cached image before queue start. Closed matches
retain their in-memory image; closed matches skipped during startup restore
have no regenerated image. All v1 responses use `Cache-Control: no-store`.

Errors use `{contract_version, request_id, error}`. Parsed request IDs survive
validation and service errors. Invalid credentials return 401 with
`WWW-Authenticate: Bearer`; permission failures return 403. Missing resources
return 404, state/revision conflicts 409, oversized bodies 413, non-JSON media
415, and schema failures 422. Capacity errors return 429 with `Retry-After: 1`;
unavailable services return 503. Unexpected failures return a generic 500.
Validation responses omit submitted values, secret fields' contents, and local
server paths.

ROM-independent HTTP checks cover setup retries, invitation claims, role and
revocation boundaries, Start dispatch, close/status reads, request bounds,
redaction, cached-image races, frame mismatch, and image recovery.

A headless live check on 2026-10-31 used an httpx ASGI client with the real
application and mGBA (no TCP listener). It created the match and both invitation
claims through HTTP, queued Start, read the completed command and committed
state, and fetched a 12,658-byte PNG at revision 1 / frame 3983. The PNG's headers
matched the observation and included `Cache-Control: no-store`. Closing through
HTTP retained the same readable PNG. ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`;
headless build:
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
Credentials and game artifacts were isolated in temporary storage and removed
at shutdown. Windowed HTTP and listening-server acceptance remain future checks.
