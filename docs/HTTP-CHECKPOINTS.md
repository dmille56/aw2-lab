# Gameplay and checkpoints over HTTP

These routes use the shared v1 models and authorization facade. Capabilities
advertise implementation separately from current runtime availability. All JSON
responses and binary exports use `Cache-Control: no-store`.

## Gameplay commands

Submit an action as the joined player for that match:

```json
{
  "contract_version": 1,
  "request_id": "REQUEST_UUID",
  "expected_revision": 1,
  "action": {"kind": "end_turn"}
}
```

Send this to `POST /v1/matches/{match}/commands`. The action union supports
`move_wait`, `attack`, `move_attack`, `move_capture`, `purchase`, `end_turn`, and `surrender`;
OpenAPI describes their typed fields. Slot and identity come from the bearer
credential and cannot be supplied in the request. The operator must claim a
separate player identity to play.

`attack` performs a stationary attack and supports indirect units. `move_attack`
also retains its empty-path form; indirect units cannot move and attack in one
turn. Load/Unload actions for APCs, Landers, and Transport Copters remain
[Milestone 5 gameplay TODOs](MILESTONE-3.org).

`202` returns a command receipt, not a claim of success. Subscribe to SSE
`command.updated` or inspect `GET .../commands/{command}` for the outcome. Turn,
revision, lifecycle, readiness, and current authorization are checked on execution.
For example, a queued stale request ends rejected with `stale_revision` and leaves
the committed boundary unchanged. An unexpected executor failure triggers the
existing rollback/recovery machinery. SSE publishes a committed state before its
terminal command event.

Preserve the request ID and exact body when retrying a lost response. An identical
retry returns the same command; changed data under that ID returns
`409 request_id_conflict`. A client timeout does not cancel queued work.

## Checkpoint creation and safe reads

`POST .../checkpoints` accepts `{request_id, expected_revision}` from the operator
or either joined player. It queues a checkpoint at a playable boundary and
returns `202`. Completion carries `checkpoint_id`; creation does not advance the
game revision or emulator frames. An initialized session is required. Creation
uses the same retry and stale-revision rules as other queued work.

`GET .../checkpoints` returns `{contract_version, checkpoints}` with this match's
references ordered by creation time and UUID. `GET .../checkpoints/{checkpoint}`
returns `{contract_version, checkpoint, compatibility}` with ROM SHA-256,
emulator build/mode, and decoder/observation schema versions. JSON reads contain
no credential verifiers, state bytes, or local paths. Both players can read during
either turn and retain access after close unless revoked. Reads use stored
artifacts and do not require an active playable session.

Unknown IDs return `404 checkpoint_not_found`; damaged stored artifacts return
`400 checkpoint_corrupt`. A checkpoint belonging to a different match is not
included in the list and returns 404 on a match-scoped read.

## Archive transfer

Only the operator can transfer archives:

- `GET .../checkpoints/{checkpoint}/archive` returns `application/zip` with a
  server-generated UUID `.zip` attachment filename.
- `POST .../checkpoints/import` accepts an `application/zip` body and a UUID
  `Request-ID` header. It returns `201` with a checkpoint reference.

Exports contain the existing full manifest, including one-way credential
verifiers, and emulator save-state data. Imports retain the store's strict
member, digest, uncompressed-size, schema, ROM/build/mode, and same-match checks.
No archive is extracted to client-selected paths. The raw upload is bounded to
4,259,840 bytes (4 MiB + 64 KiB) before decoding, regardless of Content-Length.
Oversized bodies return 413; incorrect media types return 415; missing or invalid
Request-ID headers return 422. Corrupt ZIP data returns 400; incompatible builds
or foreign matches return `409 checkpoint_incompatible`.

An import validates and stores immutable artifacts without changing CURRENT,
frames, revision, or the running match. It does not produce a command or SSE game
change. New imports need the configured runtime's compatibility identity but do
not require an initialized playable session. An identical import retry returns
the original persisted reference, including after restart with the same operator
token; it does not require a live compatibility identity to return that receipt.
Changed archive bytes under the same request ID conflict even if both ZIPs
describe equivalent content. IDs are disjoint from setup and queued commands.
New imports into a closed match fail; existing successful receipts remain retryable.

For example, with an already authenticated operator `httpx.Client`:

```python
from uuid import uuid4

archive = operator.get(f"/v1/matches/{match_id}/checkpoints/{checkpoint_id}/archive")
archive.raise_for_status()
request_id = str(uuid4())  # Preserve this and archive.content for retries.
imported = operator.post(
    f"/v1/matches/{match_id}/checkpoints/import",
    headers={"Content-Type": "application/zip", "Request-ID": request_id},
    content=archive.content,
)
imported.raise_for_status()
```

## Restoration and recovery

`POST .../checkpoints/{checkpoint}/restore` is operator-only and accepts
`{request_id, expected_revision}`. It returns `202` and runs on the mutation
queue. Restoration requires an initialized session and a compatible same-match
playable checkpoint. It can recover a `recovery_required` match. A successful
restore creates a new checkpoint and a revision above the current durable floor;
it never rewinds revisions. Its committed observation reaches SSE clients before
terminal command completion. An invalid target fails through command status;
failure after emulator loading uses the existing rollback/recovery handling.

Current authorization stays in the independent ledger: neither importing nor
restoring an old archive restores revoked player access. ROM-independent HTTP
tests cover dispatch, retries, roles, safe reads, binary bounds, restart receipts,
compatibility, corruption, recovery, and SSE publication. Live emulator and
listening-server acceptance remain in Milestone 3.
