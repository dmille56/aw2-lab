# Python SDK and player sessions

`aw2_lab.sdk.AsyncAW2Client` is an async HTTPX client for contract v1. It is
included in the Python package and uses the same typed models as the server.
Run it from the Nix project environment (`nix shell` normally, `nix develop`
for development tools). A client owns its connection pool; use `async with`
or call `aclose()`. Create one client per operator/player credential.

```python
from pathlib import Path
from uuid import UUID, uuid4
from pydantic import SecretStr
from aw2_lab.match_contract import EndTurnAction
from aw2_lab.sdk import AsyncAW2Client, WaitTimeout


async def end_turn(match_id: UUID):
    credential = SecretStr(Path("player-token").read_text().strip())
    async with AsyncAW2Client(credential=credential) as player:
        state = await player.state(match_id)
        request_id = uuid4()  # Persist with the exact operation before submission.
        receipt = await player.submit(
            match_id,
            state.summary.revision,
            EndTurnAction(),
            request_id=request_id,
        )
        try:
            result = await player.wait_for_command(match_id, receipt.command_id, timeout=30)
        except WaitTimeout:
            # Command is still accepted. Resume waiting with this command ID.
            return receipt
        return result  # Includes completed, rejected, rolled_back, or recovery_required.
```

Methods cover capabilities/readiness, create/list/inspect matches,
invitations/join/revoke, queued Start/Close, state/observations/screenshots,
gameplay actions and command status, and checkpoint create/list/inspect/export/
import/restore. Use shared `MoveWaitAction`, `MoveAttackAction`,
`MoveCaptureAction`, `PurchaseAction`, `EndTurnAction`, and `SurrenderAction`
models with `submit`. The client does not choose strategies or enumerate legal moves.
Debug HTTP operations remain available through their documented HTTP routes.

Network failures and HTTP 429/503 responses receive at most two retries by
default, with bounded exponential delay. Mutation retries preserve the same
request ID and body, including archive bytes and its `Request-ID` header.
Configure `retries=0` to disable retries. For retries across SDK calls/restarts,
persist the request ID and exact arguments; automatic IDs only persist within
one call. `TransportError.request_id` identifies uncertain submissions.
Client retries cannot determine whether a response was lost after server commit;
server deduplication resolves identical submissions.

`APIError` exposes HTTP `status` and the typed `ErrorResponse` in `response`.
`ProtocolError` identifies invalid contract responses. `TransportError` identifies
exhausted network retries. Their exception messages omit raw response bodies and
credentials. A terminal server failure is a returned `CommandResult`, distinct
from a client `WaitTimeout`. Cancellation or timeout closes local HTTP streams;
it does not cancel accepted commands. Store credentials in private files and
never put them in URLs. Redirects are disabled.

## Following changes

```python
async def follow(player, match_id, cursor=None):
    events = player.events(match_id, last_event_id=cursor)
    try:
        async for event in events:
            # Snapshot/match.updated payloads are full StateResponse objects.
            # command.updated payloads are CommandResult objects.
            apply_event(event)
            persist_cursor(event.event_id)  # Only after successful processing.
    finally:
        await events.aclose()
```

The SDK parses SSE comments and fragmented/multiline events, validates envelopes
against their framing/match, deduplicates a bounded window of IDs, and reconnects
with `Last-Event-ID` after transport failure or unexpected EOF. Retry delay and
attempt limits use the client settings. HTTP authorization errors propagate;
a closed match drains its final events and ends without reconnecting. A fresh
`snapshot` replaces local state. When `resync` is true, refresh tracked command
statuses because replay history is bounded. The application owns its cursor and
state cache. `wait_for_command` automatically checks status after snapshots to
cover missed events; it uses SSE between checks instead of repeated polling.
`wait_for_turn` waits for the requested slot, or returns a finished/closed/
recovery-required state for the host to handle. Agent decision loops remain in
the agent host. Always close event generators when breaking iteration early.

## Two interactive clients

Start the server with the ROM/operator configuration from [AUTHORIZATION.md](AUTHORIZATION.md).
Run from the repository root; keep the example directory outside the checkout.
These commands use the normal Nix-provided Python environment. Replace the
operator file path with your private file. Tokens are generated into private files,
never printed. Setup invitations expire after 15 minutes.

```sh
python examples/manage_match.py create --token-file "$AW2_OPERATOR_SECRET_FILE" --directory /tmp/aw2-sdk-demo --map-id crater_isle
```

In two separate terminals, join each slot using its own player credential:

```sh
python examples/player.py slot_1 --join --directory /tmp/aw2-sdk-demo
python examples/player.py slot_2 --join --directory /tmp/aw2-sdk-demo
```

Once both are joined, queue Start from the operator terminal:

```sh
python examples/manage_match.py start --token-file "$AW2_OPERATOR_SECRET_FILE" --directory /tmp/aw2-sdk-demo
```

Each player waits on SSE and gets a prompt during its own turn. Enter `save` to
create a checkpoint, `quit` to leave that client, or a typed action JSON object:

```json
{"kind":"purchase","property":{"x":1,"y":6},"unit_type":"Infantry"}
```

```json
{"kind":"end_turn"}
```

Use the unit lifetime ID from the displayed state when moving/attacking/capturing;
coordinates and paths follow [the match contract](MATCH-CONTRACT.md). Enter
`{"kind":"surrender"}` to finish through Yield. Returned command results include
any structured failure. The prompts use the last observed revision, so stale
requests fail through the normal server contract.

The operator can save, transfer, and restore the same match:

```sh
python examples/manage_match.py save --token-file "$AW2_OPERATOR_SECRET_FILE" --directory /tmp/aw2-sdk-demo
python examples/manage_match.py export --token-file "$AW2_OPERATOR_SECRET_FILE" --directory /tmp/aw2-sdk-demo --checkpoint CHECKPOINT_UUID --archive /tmp/aw2-sdk-checkpoint.zip
python examples/manage_match.py import --token-file "$AW2_OPERATOR_SECRET_FILE" --directory /tmp/aw2-sdk-demo --archive /tmp/aw2-sdk-checkpoint.zip
python examples/manage_match.py restore --token-file "$AW2_OPERATOR_SECRET_FILE" --directory /tmp/aw2-sdk-demo --checkpoint CHECKPOINT_UUID
```

Restore emits a new revision; clients wake on the restored state. After a server
restart using the same durable storage and operator token, launch each player
without `--join` to reuse its credential. Setup files must be preserved to resume.
The server restores its committed checkpoint and authorization ledger. Archive
import stores a checkpoint without loading it; restoration is a separate action.
Do not close the match if you intend to resume it. `close` is an operator command
with the same CLI shape as `start`.

SDK checks use real HTTP handlers with a synthetic runtime for typed state,
independent credentials, retries, gameplay and checkpoint persistence, plus
controlled streams for reconnect/resync and bounded-wait cleanup. They run with
Nix-provided Python/dependencies. Full live two-player runs in headless/windowed
mGBA and a listening server remain Milestone 3 acceptance work; these examples
do not constitute live verification.

Map selection covers Classic, Vs. Maps, Pre-Deployed, 3P Maps, 4P Maps, and War Room
profiles. Use, for example, `--map-id brace_range` for a Pre-Deployed match or
`--map-id spann_island` for War Room. Read `map_category` and `requires_unlock`
in each advertised configuration profile. Unlock-dependent maps use the local
ROM's companion `.sav`, loaded from an isolated copy; they require the relevant
purchases/unlocks in that save. Each external slot may choose any of the 19
verified COs. Income, day limit, capture limit, and CO powers can be selected
from the advertised rule options, along with Clear, Rain, Snow, or Random
starting weather. Fog remains Off.

To choose COs at creation, pass `--co-ids sami,nell`; each value must appear in
the server's `configuration_options.co_ids`. Omitting this option uses the
advertised default pair Andy/Max. For example:

```sh
python examples/manage_match.py create --map-id bean_island --co-ids sami,nell
python examples/manage_match.py create --map-id bean_island --income-per-property 2000 --day-limit off --capture-limit 20 --no-co-powers
python examples/manage_match.py create --map-id bean_island --weather rain
```

The rule flags are checked against `configuration_options.rule_options` before
match creation; omitting them uses the advertised defaults.

For a four-player team match, create with `--map-id four_corners --teams a,a,b,b`.
`--co-ids` accepts one CO per map player. Join every invitation produced by
`manage_match.py` before starting; credentials authorize only their own slot.
