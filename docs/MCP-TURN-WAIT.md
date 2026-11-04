# Bounded MCP turn waiting

`wait_for_turn(match_id, player_slot, after_revision, timeout_seconds=30)` waits
on the shared match publisher and returns an authoritative SDK state read.
`after_revision` is a nonnegative integer. The timeout must be greater than zero
and at most 60 seconds. Player credentials may wait only for their own match and
slot; operators may monitor either slot. Setup and startup keep waiting until the
deadline or a qualifying state change.

The structured result is `{contract_version: 1, timed_out, reason, state}`.
`reason` is one of:

- `turn_ready`: settled playable state, available identity, ready action boundary,
  the requested slot active, and revision strictly greater than `after_revision`.
- `finished`, `closed`, or `recovery_required`: the current lifecycle, even when
  the revision has not increased.
- `timed_out`: no qualifying boundary by the deadline; `timed_out` is true and
  `state` is the latest successful authorized SDK read.

The last 10% of the wait budget is reserved for a final state read. A turn or
terminal state found there takes precedence over timeout. If that read fails or
the entire budget expires, the tool returns a structured error instead of an old
snapshot or a fabricated timeout result. Timeout is a wait outcome, not a failed
gameplay command. A ready result does not reserve the turn: submit the chosen
action with its returned revision and handle stale-revision errors normally.

Registration captures state under the controller publication lock before SDK
reads begin. Updates during an HTTP read remain buffered; buffer overflow causes
a fresh registration and state read. Only state events wake another SDK read;
there is no polling loop or emulator/frame advancement. Waits do not hold the
command queue. They share the existing tool limits of four concurrent calls per
principal and 64 across the application, including other tools; excess calls
return `capacity_exceeded` immediately.

Cancellation via MCP `notifications/cancelled`, session termination, revocation,
and application shutdown release the publisher subscription, authorization
watchers, and SDK connection. Accepted controller commands keep their own
lifetimes. As with other MCP operations, dropping a POST connection does not
itself cancel work retained by the session. Hosts should send MCP cancellation or
DELETE their session when leaving; an abandoned wait is bounded by its deadline.
Revocation returns an authorization error or terminates the authenticated response,
never a successful timeout state. Reconnect by reading fresh state and starting
a new wait.

The agent host owns the observe/model/action loop. After an update or wait result,
it reads state, invokes its model, and submits gameplay tools when appropriate.
The server schedules no model work.

`tests/test_mcp_turn_wait.py` checks mounted MCP schemas, role/slot restrictions,
strict revision gating, setup-to-Start readiness, a turn change while waiting,
read/update races and buffer overflow, terminal/final-read outcomes, hard
deadlines, capacity, revocation, and explicit protocol cancellation. These use the
real shared queue and SDK HTTP boundary with controlled emulator observations;
live host/emulator acceptance remains a separate Milestone 4 task.
