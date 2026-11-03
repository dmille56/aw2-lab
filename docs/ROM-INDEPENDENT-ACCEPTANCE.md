# Milestone 3 ROM-independent acceptance audit

This audit covers coordination, persistence, and HTTP/SDK behavior with controlled
emulator observations. These checks require no ROM and run in the default suite.
Synthetic executors and bridge implementations supply observations, failure
conditions, and in-memory state buffers; actual HTTP routing, authorization,
queue execution, checkpoint storage, journaling, and SDK serialization are used
where described. This establishes software behavior under those inputs. Live
navigation, frontend parity, two-player gameplay, and listening-server evidence
remain separate Milestone 3 acceptance work.

## Coverage and observable claims

| Checklist requirement | Evidence | Assertions |
| --- | --- | --- |
| Concurrent submissions, execution-time stale revisions, ownership/turn checks, duplicates, conflicting IDs | [Coordination acceptance](../tests/test_coordination_acceptance.py), [controller queue](../tests/test_match_controller.py), [authorized service](../tests/test_authorized_match.py), [HTTP gameplay](../tests/test_http_gameplay_checkpoints.py) | Concurrent identical SDK submissions return one command ID and execute once. A second accepted action at the same revision becomes stale after the first commits. Both players can inspect the last committed boundary during execution, explicitly unsettled. Wrong-turn commands are rejected and changed payloads under an existing ID conflict. Queue capacity and shutdown behavior are bounded. |
| Action outcomes, illegal input, unknown menus, bounded timeouts, rollback, failed recovery | [Action navigation](../tests/test_action_navigation.py), [coordination acceptance](../tests/test_coordination_acceptance.py), [move/wait](../tests/test_move_wait_executor.py), [move/attack](../tests/test_move_attack_executor.py), [checkpoint recovery](../tests/test_match_checkpoint.py), [HTTP recovery](../tests/test_http_gameplay_checkpoints.py) | Invalid paths/units and conservative combat restrictions fail before input. Unknown menus are rejected; a stalled confirmation exhausts its frame budget and an unresponsive input call triggers its wall watchdog with diagnostics. Post-input failures restore emulator state and identity metadata with a fresh revision. Failed input release/restore stops gameplay; explicit checkpoint restore can recover it. These tests do not establish that every unexpected emulator screen has been researched. |
| Identity continuity/replacement, metadata round trips, compatibility, revision changes | [Observation tracker](../tests/test_match_observation.py), [unit ledger](../tests/test_unit_identity.py), [checkpoint store](../tests/test_checkpoint_store.py), [checkpoint service](../tests/test_match_checkpoint.py), [SDK](../tests/test_sdk.py) | Movement preserves lifetime IDs; destruction and reusable RAM slots do not alias old units. Checkpoints round-trip identities and save-state bytes. Incompatible builds/ROMs/schema identities and foreign matches fail before loading. Restore and rollback advance above durable revision floors; debug mutations invalidate gameplay identity. Corrupt artifacts and ledger disagreements are rejected. |
| Restart at journal/checkpoint boundaries, unfinished commands, corrupt artifacts, durable retries | [Coordination acceptance](../tests/test_coordination_acceptance.py), [JSONL journal](../tests/test_command_journal.py), [checkpoint recovery](../tests/test_match_checkpoint.py), [authorization recovery](../tests/test_authorized_match.py), [checkpoint store](../tests/test_checkpoint_store.py) | Acceptance persists before queueing, and recovery checkpoints precede mutation. Accepted-only work is rejected after restart; running work without a commit is rolled back without replay. A missing terminal journal entry after CURRENT commit is reconciled as the committed result, restores state at a fresh revision, and returns the same receipt on retry without another capture. Interrupted close honors the closed ledger. Partial artifact/pointer writes retain the prior commit; complete malformed journal records are rejected. |
| HTTP serialization/errors/ownership, SDK retries/completion | [Shared schema/error map](../tests/test_api_contract.py), [HTTP API](../tests/test_http_api.py), [HTTP gameplay/checkpoints](../tests/test_http_gameplay_checkpoints.py), [SSE HTTP](../tests/test_http_events.py), [SDK](../tests/test_sdk.py), [debug API](../tests/test_http_debug.py) | Every error enum has a mapped HTTP status; schema/media/body errors are bounded and redacted. Slot/operator scopes and revocation apply to reads, writes, retries, and streams. Lost-response SDK retries reuse exact request bytes and ID. SSE reconnect sends the cursor, resynchronizes missed command status, rejects inconsistent envelopes, and closes streams on timeout. Client wait expiry does not send cancellation. Terminal results preserve structured failures. |

## Added gap coverage

`test_sdk_concurrent_duplicate_and_stale_submissions_execute_once` holds a
synthetic executor at a gate while independent SDK clients submit/read through
real HTTP handlers. Assertions verify committed revision, receipt identity, and
executor call count rather than relying on task timing or sleeps.

`test_restart_after_current_commit_before_terminal_record_returns_committed_receipt`
constructs the durable files present at that exact crash boundary, invokes the
application's startup recovery helper, and checks restored observations, the
original terminal receipt, one terminal journal record, and no extra capture
on retry. Existing tests cover accepted-only/running-without-commit recovery,
interrupted close, operator-generation changes, and import receipts after restart.

`test_journal_failure_never_reports_public_gameplay_success` injects disk errors
at running and terminal appends. A failed running append prevents execution;
a failed terminal append after execution cannot publish success. Both outcomes
stop new acceptance and keep the public match in recovery-required state with a
coherent last committed observation. The journal tests separately cover failed
acceptance writes, complete malformed records, repair of an incomplete final
record, repeated reads after repair, and safe storage diagnostics.

The new navigation check uses an outer one-second test deadline, a deterministic
three-frame navigation budget, and a short watchdog for an input coroutine that
never returns. Its assertions distinguish unknown-menu rejection, exhausted
frame budget, and wall-clock expiry. Existing checkpoint tests verify rollback
and failure behavior after a synthetic navigation timeout.

## Verification

Run the complete repository gate in the normal Nix environment:

```sh
pre-commit run --all-files
# If required tools are missing:
nix develop -c pre-commit run --all-files
```

The focused additions can be run with:

```sh
pytest tests/test_command_journal.py tests/test_coordination_acceptance.py
```

During this audit, the Codex filesystem sandbox could hang when asyncio worker
threads returned filesystem operations. Running the same repository hooks outside
that sandbox completed. This is an execution-environment limitation; no test was
skipped or disabled to make the gate pass. The default opt-in emulator tests keep
their normal ROM/artifact-dependent skips.
