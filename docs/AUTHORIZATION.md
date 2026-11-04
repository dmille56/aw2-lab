# Shared authorization and setup service

The server can load an operator credential with `--operator-secret-file PATH`
(or `AW2_OPERATOR_SECRET_FILE`). The file must be outside the source checkout
and Nix store, contain one 32–128-character token with an optional final newline,
and be an owner-only regular file on POSIX. Symlinks are rejected. The token is
read once at startup and never returned by the application.

For local provisioning, enter the project Python environment, then generate the
file without printing its contents:

```sh
mkdir -p ~/.config/aw2-lab
chmod 700 ~/.config/aw2-lab
(umask 077; python -c 'from pathlib import Path; import secrets; p = Path("~/.config/aw2-lab/operator-token").expanduser(); p.open("x").write(secrets.token_urlsafe(32) + "\n")')
```

Exclusive creation preserves an existing token. Point `--operator-secret-file`
at that file when starting the normal server with your own ROM. Player and
invitation clients must independently generate tokens using an OS-backed random
source. Length validation cannot prove randomness. Python's
[`secrets.token_urlsafe(32)`](https://docs.python.org/3/library/secrets.html)
uses 32 bytes of randomness; comparisons use `hmac.compare_digest`.

The [HTTP lifecycle and read routes](HTTP-API.md), SDK clients, and authenticated
MCP tools use this shared service layer. MCP player credentials are sent in the
transport bearer header; invitation and join credentials remain in trusted host
provisioning and are not model-visible tools. See
[MCP host integration](MCP-INTEGRATION.md).
Without an operator file, no
`AuthorizedMatchService` is installed. An existing authorization ledger requires
the operator file on subsequent startup; omitting it cannot enable legacy
checkpoint authentication.

## Service boundary

`AuthorizedMatchService` is the entry point for HTTP and future transport adapters.
Authenticate the bearer credential to obtain a trusted principal; never construct
that principal from client/model-supplied role, slot, or generation fields.

- Operators create/discover matches, issue invitations, revoke slots, start/close,
  and transfer/restore checkpoint archives. Gameplay requires a separate player
  credential. Debug access also requires the startup enablement flag on the
  authorization service, disabled by default.
- Joined players can inspect their own match during either turn, submit their
  own slot's gameplay, and create checkpoints. AW2 turn/revision/readiness checks
  remain in the controller. Archive transfer/restore is operator-only.
- Closing retains read access for existing players but invalidates invitations
  and blocks mutations. Operators can revoke retained read access. Operator
  close is allowed while recovery is required.

The controller's low-level observation and recovery methods remain trusted
internal primitives. Adapters must use the access-checked facade for reads,
waits, and command status. With authorization configured, controller mutations
require principals and unrestricted `join_slot` is disabled. Existing isolated
emulator research/tests can still explicitly instantiate a controller without
an authorization service; this is not a public match API mode.

## Durable metadata and retries

`authorization.json`, beside the configured checkpoints and command journal,
contains setup summaries, slot generations, SHA-256 token verifiers, invitation
state, and metadata request deduplication. Raw operator, invitation, and player
tokens never enter this file or the command journal. The file is private; do not
track, export, edit, or restore it with emulator checkpoints.

One server process owns the storage root. Metadata writes use a process-local
lock, candidate-state validation, a private temporary file, fsync, atomic rename,
and directory fsync before acknowledgement. The ledger is bounded to 16 MiB;
it does not silently evict retry history. A failed persistence operation disables
authorization for that instance until restart, including uncertain post-rename
failures. Missing/inconsistent records block checkpoint adoption before emulator
input. Corrupt or non-private ledger files block startup.

Creation resolves an omitted configuration only on first use. Retries retain the
original match and resolved configuration. Invitation issuance retries preserve
its original ID and expiry, even after replacement/consumption. Joining atomically
consumes a valid invitation and binds the caller-generated player credential;
a lost response can be retried with the same credential and request after the
invitation expires. Changed payloads conflict. Another credential cannot replay
the claim; revoked claims cannot return cached responses.

Revoking clears the active verifier, invalidates invitations, increments the slot
generation, and wakes registered revocation listeners. Identical revoke retries
return the original result and cannot revoke a subsequent replacement claim.
Replacement claims are allowed only during setup. Revocation changes neither
emulator frames nor game revision and does not surrender the army. Previously
used player/invitation secrets cannot be assigned again.

## Queue, waits, and recovery

Authorization runs before cached receipts and again before queued execution,
including after recovery-checkpoint capture and before gameplay/input begins.
Fingerprints bind player commands to match/slot/generation and operator commands
to the singleton operator role, without storing raw credentials. The operator's
process generation still gates authorization but is excluded from durable
fingerprints, so authenticated retries survive restart. Revoked queued work is rejected. An already executing action may
finish; its resulting state preserves the ledger's current revoked-slot metadata.

The facade's command wait registers a revocation wakeup and rechecks before
returning a result. Revocation ends that wait without cancelling the accepted
action. SSE registers that same wakeup, drops pending data when revoked, and
rechecks permissions for each live/replayed event and heartbeat. Disconnect,
overflow, close, and shutdown release subscription resources. MCP delivery must
use these shared checks when its transport is implemented.

A setup restart restores claims/invitations and stays in setup until explicit
start. Playable recovery requires a compatible checkpoint and current ledger.
Checkpoint slot statuses and credential hashes never overwrite the ledger;
archive import, restore, and restart cannot undo revocation or consumed invites.
A checkpoint for a durably closed match is not reopened during application
startup. If close persisted CLOSED before its terminal journal append, startup
reconciles that interrupted close as completed from the ledger before considering
checkpoint recovery; repeated recovery does not append duplicate terminal events. Without a playable checkpoint, non-setup active metadata fails recovery
closed rather than inventing battlefield state.

Rotate the operator token through a controlled server restart. Old tokens and
old in-process operator principals are invalid in the new server instance.

## Verification

`test_authorization.py` covers metadata retries, expiry/replacement/consumption,
role/resource permissions, revocation/replacement, rotation, private token files,
ledger corruption, and write failure. `test_authorized_match.py` covers cached
receipts, queued revocation, running actions, wait wakeups, checkpoint roles,
import/restore/restart retaining revocation, missing-ledger rejection before
input, closed-checkpoint recovery, and setup restart. CLI/application tests cover
operator file wiring and startup recovery. These are ROM-independent checks;
this change adds no live-emulator verification claim.
