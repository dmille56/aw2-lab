# HTTP API v1

The implemented lifecycle, read, and SSE routes use the shared authorization service
and match controller. `/health` retains its existing public payload. The public
`GET /v1/capabilities` describes the verified configuration, implemented routes,
runtime availability, production units, and limits. `GET /v1/readiness` reports
server and match readiness to the operator. Gameplay submission and checkpoint
operations use the shared queue and services. Debug operations require `--enable-debug-api` and the operator credential. MCP
gameplay remains unavailable.

Capabilities report the supported game-contract, match-observation, and nested
game-state schema versions. Clients should check these before using match routes;
each response must still validate its own contract and schema versions.

Start the normal server with your local ROM and the operator file described in
[AUTHORIZATION.md](AUTHORIZATION.md). With no operator file configured, match
routes return `503 runtime_unavailable`. Use the default loopback address
`http://127.0.0.1:43127`. Browser cross-origin access is disabled by default.

JSON payloads carry `contract_version: 1` (omission defaults to 1). Request models
and the error envelope are published in `/openapi.json` and `/docs`. Ordinary
JSON bodies are limited to 65,536 bytes; JSON mutation routes require
`Content-Type: application/json`. Archive import instead requires `application/zip`
with a 4-MiB-plus-64-KiB upload limit. Secrets belong in bearer headers or the
invitation request fields, and never in URLs.

| Route | Permission | Success |
| --- | --- | --- |
| `GET /v1/capabilities` | Public | 200, capabilities |
| `GET /v1/readiness` | Operator | 200, independent server/runtime/match readiness |
| `POST /v1/matches` | Operator | 201, summary and `Location` |
| `GET /v1/matches` | Operator | 200, match list |
| `GET /v1/matches/{match}/identity` | Operator or that match's player | 200, authenticated role and player slot |
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
| `GET /v1/matches/{match}/events` | Operator or that match's player | 200, SSE stream |
| `POST /v1/matches/{match}/commands` | That slot's player | 202, command receipt |
| `POST /v1/matches/{match}/checkpoints` | Operator or that match's player | 202, command receipt |
| `GET /v1/matches/{match}/checkpoints` | Operator or that match's player | 200, checkpoint references |
| `GET /v1/matches/{match}/checkpoints/{checkpoint}` | Operator or that match's player | 200, reference and safe compatibility metadata |
| `GET /v1/matches/{match}/checkpoints/{checkpoint}/archive` | Operator | 200, ZIP attachment |
| `POST /v1/matches/{match}/checkpoints/import` | Operator | 201, checkpoint reference |
| `POST /v1/matches/{match}/checkpoints/{checkpoint}/restore` | Operator | 202, command receipt |

Both player slots can inspect their own match during either turn. Closing keeps
their retained read access; revocation invalidates it immediately, including
cached screenshots and command results. Operator credentials cannot play a slot.

See [match events over SSE](HTTP-EVENTS.md) for event envelopes, reconnect/replay,
resynchronization, buffer limits, revocation, and a streaming client example.
See [gameplay and checkpoints](HTTP-CHECKPOINTS.md) for command bodies, archive
transfer, retry semantics, and recovery.

Creation accepts an omitted configuration or the complete verified profile from
capabilities. Select a complete entry from `configuration_profiles` using
`default_profile_id`; its `configuration` can be submitted unchanged. The
`configuration_options` descriptors summarize those verified choices, with
`combination_constraint: verified_options`: select advertised values for each
independently configurable field. Profile selection does not depend on emulator
availability; Start reports whether the runtime is available.

The default profile uses Bean Island. Map selection supports 72 two-player maps across
Classic (17), Vs. Maps (21), Pre-Deployed (12), and War Room (22), each advertised as
`<map_id>_v1`. These profiles use external Andy/Red/team A and Max/Blue/team
B, fog Off, Clear weather, income 1,000 per property, a 30-day limit,
capture limit Off, and CO powers On. Any pair from the 19 advertised COs is
selectable; player colors, teams, and controls remain fixed. Income, day limit,
capture limit, and CO power availability are configurable. Fog and starting
weather remain fixed. Creation validates before allocating a match or touching
the emulator. Unsupported assignments, fog/weather, internal CPU control, and
the future three/four-player shape return
`422 unsupported_feature`. Unknown map/CO IDs, duplicate colors, invalid slot
ordering, incomplete configurations, and malformed values return
`422 invalid_request`. Map IDs outside the advertised two-player Versus catalog
are rejected. Failed validation allocates no
match and does not reserve the request ID.

The shared schema retains two to four ordered slots with explicit CO, color,
team, and control fields for future expansion; current capabilities advertise
only two external players. Expanded support requires setup and gameplay
verification before adding a profile.

The rule field `weather` accepts `clear`, `rain`, `snow`, and `random`.
Clear/Rain/Snow select weather for the entire match; Random allows weather to
change during play. Only `clear` is currently advertised and executable;
the other three values return `422 unsupported_feature`. Unknown values return
`422 invalid_request`. The former public spelling `starting_weather` is rejected,
including when supplied alongside `weather`. Existing controller checkpoints and
authorization ledgers retain their stored `starting_weather` field; the adapter
exposes it as `weather` in capabilities and match responses without rewriting
stored documents.

The rule field `day_limit` is required and accepts Off as JSON `null`, or an
integer from 5 through 99 inclusive. All these limits are advertised and
executable.
Integers 1–4, out-of-range numbers, booleans, floats, and strings return
`422 invalid_request`. Existing controller/checkpoint and authorization-ledger
schemas retain their original field spelling; selected values are carried in
the durable match configuration.
Legacy limits of 1–4 cannot be converted to the public schema and are rejected
without silently changing them. Off is stored as `null` and selected directly;
it is not converted to a numeric sentinel or replaced with the default limit.

`income_per_property` accepts the advertised values 1,000 through 5,000 in
500 increments. `co_powers` accepts `true` or `false`. Capabilities enumerate
these values alongside day and capture limits. First-turn funds are verified
against the selected income and each map's observed owned properties.

The rule field `capture_limit` is required in an explicit configuration and
represents the Capture Properties victory rule. Use JSON `null` for Off, or an
integer from 12 through 27 inclusive for the number of properties needed to win.
Off and limits from 12 through 27 are advertised and executable. Out-of-range
values, booleans, floats, strings, and missing fields return `422 invalid_request`.
Omitting the entire configuration
still selects the default profile, including capture limit Off. Legacy
controller/checkpoint and authorization-ledger records without a capture-limit
field translate to Off. New records preserve the selected numeric limit.

Preserve `request_id` and the exact request when retrying a lost
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
    response = operator.get("/v1/capabilities")
    response.raise_for_status()
    capabilities = response.json()
    profile = next(
        entry for entry in capabilities["configuration_profiles"]
        if entry["profile_id"] == capabilities["default_profile_id"]
    )
    response = operator.post("/v1/matches", json={
        "request_id": str(uuid4()), "configuration": profile["configuration"],
    })
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

Readiness requires the operator bearer credential. It does not advance frames
or probe the bridge while a command may be running. `emulator` reports process
availability; `bridge` reports whether a configured runtime is attached to the
running emulator; `queue` reports whether commands can be accepted. `recovery`
is `in_progress` while a command executes, `required` for a recovery-required
match, and `not_required` otherwise. `match_ready` is true only for an active
playable match with the runtime configured. A responsive server with no match
still returns 200 with `match_ready: false`.

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

Debug routes under `/v1/matches/{match}/debug` accept POST requests for
`buttons`, `frames`, `reset`, `memory/read`, and `memory/write`. Mutations use
`request_id` and `expected_revision`, returning a queued command receipt.
Buttons use `buttons: ["a"]` and `frames: 1`; frames accepts 1–600. Memory reads
use `expected_revision`, `address`, and `length` (1–4096); writes use `request_id`,
`expected_revision`, `address`, and canonical base64 `data` (1–256 decoded bytes).
Access is limited to EWRAM [0x02000000, 0x02040000) and IWRAM
[0x03000000, 0x03008000), advertised in `debug_memory_regions`. Reads require
a playable boundary and execute on the queue without changing revisions.
Every successful debug mutation publishes a new revision with unavailable
battle data and identities, and ends as `recovery_required`. Restore a prior
checkpoint before gameplay resumes. Debug is disabled by default.

Use [the typed Python SDK and two-player examples](PYTHON-SDK.md) for async
HTTP methods, SSE subscriptions, retry-safe commands, and checkpoint workflows.

To select a map, submit its complete advertised profile to match creation. For
example, select `crater_isle_v1` from capabilities and use its `configuration`.
The operator example accepts `--map-id crater_isle` on `create`:

```sh
python examples/manage_match.py create --token-file /path/to/operator-token --map-id crater_isle
```

Select advertised rule values at creation with `--income-per-property`,
`--day-limit`, `--capture-limit`, and `--co-powers`/`--no-co-powers`. For example:

```sh
python examples/manage_match.py create --token-file /path/to/operator-token --map-id crater_isle --income-per-property 2000 --day-limit off --capture-limit 20 --no-co-powers
```

The selected map is persisted in match metadata and checkpoints. Start verifies
its numeric ROM ID, dimensions, two external armies, selected rules, and opening
property income before publishing a playable boundary. A wrong loaded map fails
startup. Profiles include `map_category` (`classic`, `versus`, `pre_deployed`, or
`war_room`) and `requires_unlock`. Eight entries require purchases/unlocks in the
local cartridge save: Hourglass Isle, Big Daddy, Pay Dirt, Long Road, Nest Egg,
The Trident, Banker Hills, and Missile Plains. A fresh save cannot start those
profiles; the failed Start retains an actionable menu diagnostic and enters
recovery-required without publishing a playable observation. Close that match
before choosing another map.

The launcher explicitly loads an isolated copy of the ROM's companion `.sav`;
source saves are never changed. Unlocks are not granted or patched by the server.
3P Maps, 4P Maps, and maps with three/four armies in Pre-Deployed or War Room
remain tied to the player-count expansion. Custom maps remain deferred.
