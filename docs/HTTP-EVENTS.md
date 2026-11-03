# Match events over SSE

`GET /v1/matches/{match_id}/events` accepts the same bearer header as match reads.
The operator and either joined player can subscribe during either player's turn.
Missing/invalid credentials return 401; another match's player gets 403. Without
operator provisioning the route returns 503. Capability `http_sse` reports this
separately from future MCP subscription support.

The response is `text/event-stream`, with `Cache-Control: no-store` and
`X-Accel-Buffering: no`. The application does not compress or buffer the stream.
Each event has an SSE `id`, `event`, and single JSON `data` line. The JSON envelope
has `contract_version: 1`, `match_id`, `event_id` matching the SSE ID, `event`
matching the SSE event name, and `payload`:

| Event | Payload |
| --- | --- |
| `snapshot` | Complete `StateResponse`; envelope also includes `resync` |
| `match.updated` | Complete `StateResponse` after lifecycle, slot, or committed-boundary changes |
| `command.updated` | Complete `CommandResult` for queued, running, or terminal status |

The typed schemas live in `aw2_lab.match_events`; OpenAPI exposes their JSON
schema as `x-event-schema` on the event stream's content schema. These shared
events are independent of HTTP framing and can be consumed by a future MCP
adapter. MCP resources/notifications and agent decision loops are not implemented
by this endpoint; decision loops belong to the agent host.

An initial snapshot and subscriber registration are atomic with publication.
State includes the last committed observation; while executing, it retains that
observation and reports `settled: false`. Publication never captures intermediate
animation frames. A completed mutation publishes its committed state before its
terminal command result, after the required persistence writes. Setup claims and
revocations publish state without changing game revision. Identical metadata
retries do not publish a new state. Screenshots remain on the PNG endpoint;
fetch the image for the reported revision when needed.

To reconnect, preserve the last processed event ID and send `Last-Event-ID` (at
most 128 characters). IDs are opaque server-run UUID/sequence cursors, separate
from game revision. Retained subsequent events replay in order. Duplicate
delivery is possible; deduplicate IDs. Unknown, expired, or previous-run cursors
produce a fresh `snapshot` with `resync: true`. A replay too large for the pending
subscriber buffer also resynchronizes. Replace local state on a snapshot; after
resync, explicitly inspect any tracked commands whose terminal results may have
been missed. The stream promises no durable event history.

Replay retains at most 256 events or 16 MiB per match. Each subscriber can hold
at most 128 pending events or 8 MiB; JSON envelope bytes count toward these
limits. An overflowing subscriber is disconnected and its pending data dropped;
it may reconnect with backoff to replay/resynchronize. Network writes do not hold
controller locks or block command execution. A single snapshot exceeding the
subscriber byte limit also disconnects.

Comment heartbeats arrive every 15 idle seconds, with no event ID, game revision,
or frame change. Slot revocation drops queued delivery and wakes idle streams;
every live/replayed delivery rechecks current access. Already sent bytes cannot
be recalled. Disconnects release buffers and authorization watchers. Closing a
match sends its final state and terminal command event, then ends the stream;
a new subscription to a retained closed match sends one snapshot and ends.
Controller shutdown closes streams. The CLI bounds HTTP graceful shutdown to
five seconds before lifespan cleanup so idle SSE connections cannot keep the
server alive indefinitely; external ASGI runners should also bound their drain.

For a single connection with a private player token file (reconnect handling will
also be provided by the planned SDK):

```python
import json
from pathlib import Path

import httpx

player_token = Path("~/.config/aw2-lab/player-token").expanduser().read_text().strip()
match_id = "MATCH_UUID_FROM_JOIN"
last_event_id = None  # Restore the application's last successfully processed cursor.
headers = {"Authorization": f"Bearer {player_token}"}
if last_event_id is not None:
    headers["Last-Event-ID"] = last_event_id
with httpx.stream(
    "GET", f"http://127.0.0.1:43127/v1/matches/{match_id}/events",
    headers=headers, timeout=httpx.Timeout(30, read=None),
) as response:
    response.raise_for_status()
    for line in response.iter_lines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            # Apply the state/command update before persisting its cursor.
            last_event_id = event["event_id"]
```

Browser clients use a fetch-based SSE reader to send the bearer header; native
`EventSource` cannot set it. Do not put credentials into query parameters.
ROM-independent tests cover controller ordering and incremental ASGI delivery;
live emulator and listening-server acceptance remain in Milestone 3.
