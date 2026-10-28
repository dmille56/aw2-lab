# Checkpoint and journal commit protocol

This document defines the crash-safe commit order for the local checkpoint
store. The configured storage root is trusted server configuration, outside the
Git checkout and Nix store. Clients refer to checkpoint IDs; they never choose
paths. There is one writer, the serialized match controller.

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

Acceptance and execution events are flushed to the journal before the receipt
is returned and before the action starts. After an action reaches a validated
boundary, the controller commits its state in this order:

1. Capture mGBA state and save RAM, plus the matching summary, observation
   revision, frame, and identity metadata, while still on the serialized lane.
2. Write the state blob to a temporary file in the checkpoint directory; flush
   and `fsync` it; rename it to its immutable checkpoint filename; then `fsync`
   the directory.
3. Write the manifest to a temporary file in that directory; flush and `fsync`
   it; rename it to its immutable filename; then `fsync` the directory.
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
