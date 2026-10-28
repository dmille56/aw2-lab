# Checkpoint and journal commit protocol

This document defines the crash-safe commit order for the local checkpoint
store. The storage root defaults to the per-user data directory
(`$XDG_DATA_HOME/aw2-lab` on Linux,
`~/Library/Application Support/aw2-lab` on macOS, and `%LOCALAPPDATA%/aw2-lab`
on Windows). Set `AW2_STORAGE_DIR` or pass `--storage-dir PATH` to choose
another trusted local directory. The server rejects paths inside the source
checkout or `/nix/store`. Checkpoints live under `checkpoints/`; the append-only
journal is `commands.jsonl`. Clients refer to checkpoint IDs; they never
choose paths. There is one writer, the serialized match controller.

## Stored records

- A state blob contains the mGBA savestate, including save RAM. Its immutable
  manifest records the state digest and length, ROM/build/schema identities,
  match summary and revision, frame, and unit identity ledger.
- `CURRENT` is a `CheckpointCommitPointer`. It identifies the checkpoint and
  manifest digest that represent the last committed state. For a command
  checkpoint it also carries the terminal `CommandResult`; for a standalone
  checkpoint this is null.
- The command journal is append-only JSONL. Accepted, running, and terminal
  events carry command/request IDs, redacted payload and fingerprint, revisions,
  result, and an optional checkpoint ID on the terminal event.

## Commit order

Acceptance is flushed to the journal before the receipt is returned. Before an
emulator mutation is recorded as running, the controller asks the installed
checkpoint service to capture the last settled playable boundary. The service
writes an immutable recovery checkpoint without changing `CURRENT`; only after
it is durable does the running event include its recovery checkpoint ID. If
capture fails, the command is rejected before its handler can touch the
emulator. Explicit checkpoint restoration skips this pre-action capture because
it is itself the recovery operation.

When an emulator mutation fails after execution starts, the controller uses the
recovery checkpoint ID from that command's journal record. The checkpoint
service validates and loads the saved emulator state, reconstructs the unit
identity ledger, advances the observation revision beyond the live and durable
revision floors, and verifies a settled playable boundary. It then commits a
fresh checkpoint and terminal `rolled_back` result before publishing the
restored observation. If any restore or validation step fails, the tracker
remains unavailable and the match enters `recovery_required`.

After an action reaches a validated boundary, the controller commits its state
in this order:

1. Capture mGBA state and save RAM, plus the matching summary, observation
   revision, frame, and identity metadata, while still on the serialized lane.
2. Write `state.bin` in a private staging directory under the storage root;
   flush and `fsync` it.
3. Write `manifest.json` in the same staging directory; flush and `fsync` it,
   then `fsync` the staging directory. Rename the complete directory to the
   checkpoint UUID and `fsync` the storage root. Readers can now see the complete
   immutable pair.
4. Write a temporary `CheckpointCommitPointer` naming the checkpoint and
   manifest digest. Include the command result and command ID when this state
   commits a command. Flush and `fsync` the temporary file, atomically replace
   `CURRENT`, and `fsync` its directory. This replacement is the durable state
   commit point.
5. Append and flush the terminal journal event, including the checkpoint ID.
6. Publish the new observation, summary, and command result to readers.

All temporary and final files must be on the same filesystem so rename is
atomic. A checkpoint pointer must never refer to a blob or manifest that has
not already been renamed and directory-synced. Non-mutating commands without a
checkpoint append their terminal event before publishing their result.

## Crash handling

- A crash before the `CURRENT` replacement leaves the prior committed pointer
  intact. Any newly written blob or manifest is an orphan and is ignored. An
  accepted/running command without a terminal record is left unresolved and is
  never replayed automatically.
- A crash after `CURRENT` is durable but before the terminal journal append is
  reconciled by matching the unresolved command ID and request ID to the
  pointer's embedded terminal result and the manifest's originating command
  ID. Recovery can then append the missing terminal event without rerunning the
  action.
- A crash after the terminal event but before in-memory publication restores
  from `CURRENT` and uses the terminal journal event as the command result.
- A missing file, digest mismatch, malformed pointer, or disagreement among
  pointer, manifest, command result, and journal requires recovery. Do not fall
  back to an older pointer or replay an unresolved game action silently.

The storage implementation must validate every hash and cross-reference before
loading emulator state. Diagnostics for partial writes, corrupt artifacts, and
unavailable storage are defined below; persistence integration and recovery
remain open checklist work.

## Failure diagnostics

Persistence failures use stable `ErrorCode` values and bounded details; messages
never include the configured local path:

- `storage_unavailable` identifies the failed operation, exception class, and
  OS error number when available. Journal append failures stop command
  acceptance. A terminal append failure leaves the match recovery-required.
- `journal_corrupt` reports malformed complete records with a line number. An
  incomplete final JSONL record is truncated to the last complete newline,
  `fsync`ed, and returned as a diagnostic with its discarded byte count; the
  caller must reconcile unresolved commands before accepting new work.
- `checkpoint_corrupt` identifies a missing pointer, manifest, or state blob;
  malformed metadata; pointer/manifest disagreement; size mismatch; digest
  mismatch; or restored-frame mismatch.
- `checkpoint_incompatible` reports the mismatched ROM, emulator build/mode, or
  schema fields before the bridge is asked to load state.

These diagnostics distinguish a repairable incomplete journal tail from a
malformed complete record. They do not authorize replay or fallback to an older
checkpoint. Recovery remains explicit when the committed state is uncertain.

## Checkpoint service

`CheckpointStore` implements the local files and `CURRENT` protocol. It uses a
trusted root supplied by server configuration on a local filesystem supporting
atomic rename and directory `fsync` (verified with the synthetic checks on
NixOS). `MatchCheckpointService` supplies the authenticated operations:

| Operation | Inputs | Result |
| --- | --- | --- |
| `create` | Match ID, joined credential, request ID, expected revision | Queued command; its terminal result contains `checkpoint_id` |
| `export` | Match ID, checkpoint UUID, joined credential | ZIP archive bytes |
| `import_archive` | Match ID, archive bytes, joined credential | Checkpoint reference; does not load the emulator or change `CURRENT` |
| `restore` | Match ID, checkpoint UUID, joined credential, request ID, expected revision | Queued command; a successful result has a fresh revision and new checkpoint UUID |

Create and restore run on the same controller lane as gameplay and debug
mutations. A successful checkpoint commit precedes the terminal journal event
and observation publication. The controller returns the checkpoint UUID in
`CommandResult`; no server path is part of an operation input or result.

Archives have exactly two uncompressed members, `manifest.json` (at most 1 MiB)
and `state.bin` (at most 3 MiB), with a bounded total archive size. Import reads
members into memory and never extracts archive paths. Extra members, duplicate
names, compression, encryption, invalid metadata, and state digest/size
mismatches are rejected. An existing checkpoint UUID can be imported again
only when its manifest and state match exactly.

The service currently restores checkpoints belonging to the same active match
and fixed configuration, with the same ROM, build, and frontend mode. Creation
and restoration require the observer's supported playable-turn boundary;
finished/setup checkpoints are not advertised as restorable. Restore preserves
the current joined credentials and slot claims, restores the saved unit ledger,
and commits above the live tracker, controller, source checkpoint, and current
pointer revisions. The saved frame and active unit records are checked before
the restored observation is published. Failures after loading block gameplay
until an explicit successful restore.

Executors and the service share a `CheckpointSession`; after restoration,
executors must use its replacement `tracker`. The service receives an injected
game-state capture function and bridge, so synthetic checks need no ROM.
The default storage root and durable journal are wired into server startup;
`CheckpointStore` is available as `app.state.checkpoint_store` for the
checkpoint service. HTTP/SDK routes, restart adoption of a saved match, and
durable journal replay remain later checklist items. The current
checks verify filesystem/archive/controller behavior with a synthetic emulator;
they do not claim a new live mGBA end-to-end checkpoint run.
