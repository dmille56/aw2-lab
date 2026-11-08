# Live MCP gameplay acceptance

The opt-in checks in [test_mcp_live_acceptance.py](../tests/test_mcp_live_acceptance.py)
launch the actual API/emulator process on an ephemeral loopback port and use the
pinned Python MCP SDK's Streamable HTTP client. One player uses the HTTP SDK while
the other uses an independent MCP session, or both players use independent MCP
sessions with separate bearer credentials. A deterministic test driver invokes
the high-level tools; this is MCP client interoperability evidence, not a model
host run.

## Reproduction

Provide the supported ROM and, for windowed mode, a working display. The test
creates fresh credentials with mode 0600 and isolated server storage under
pytest's temporary directory. Keep the selected evidence directory outside Git
and the Nix store.

```sh
AW2_RUN_MCP_LIVE_TESTS=1 AW2_ROM_PATH=/absolute/path/to/aw2.gba \
  nix develop -c pytest -s tests/test_mcp_live_acceptance.py \
  --basetemp=/tmp/aw2-mcp-live
```

Use `-k 'headless'` or `-k 'windowed'` to select a mode. The test covers
purchase, an exact durable-retry replay, movement/wait, partial capture, turn
changes, surrender, cross-client state agreement, and an MCP screenshot whose
revision matches the terminal state. MCP command results are polled with
`get_command`, retaining the command ID returned by each accepted call.

## Recorded results (2026-11-08)

All four protocol/mode combinations passed with the supported ROM
SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`:

| Human slot client | Opposing slot client | Mode | Result |
| --- | --- | --- | --- |
| HTTP SDK | MCP host session | Headless | Passed |
| HTTP SDK | MCP host session | Windowed | Passed |
| MCP host session | Independent MCP host session | Headless | Passed |
| MCP host session | Independent MCP host session | Windowed | Passed |

The MCP host sessions authenticated independently and observed one shared match.
The blue player's repeated purchase returned the original command ID. Both
clients completed turns; the run captured a neutral property partially and
finished by surrender. The MCP screenshot metadata matched the terminal
revision. Headless screenshot: revision 14/frame 6178, SHA-256
`6e660dce9fe4f51f2473670c225186c6effae64275f18d74ce9a9b2c872c67d6`.
Windowed screenshot: revision 14/frame 6210, SHA-256
`db09afcf7f17d2cb8adc2c42295bf040ff323394009918e46a18fbd68014a37b`.

The run artifacts are under `/tmp/aw2-mcp-live-headless/` and
`/tmp/aw2-mcp-live-rest/`. The directories contain generated credentials,
operator storage, command journals, and server logs; treat them as private test
data.

## Checkpoint, restart, notifications, and bounded turn wait (2026-11-08)

`test_live_mcp_checkpoint_restart_notifications_and_wait` passed in headless and
windowed mode with the supported ROM and MCP SDK 1.29.0. It creates a checkpoint
through MCP, exports and reimports its archive, changes the match, restores via
MCP, and confirms the state and unit identities match the saved boundary. An
existing HTTP client observes the same restored state. A clean API/emulator
restart recovers that boundary; retrying the original MCP purchase request ID
returns the original command receipt without changing the resumed state.

An independent MCP host received real `notifications/resources/updated` events
for the subscribed state resource during restore. A fresh session reconnected,
resubscribed, and read the committed resource. The bounded `wait_for_turn`
timeout returned `timed_out` in both modes. The tests use deterministic host
drivers, not a model host.

| Mode | mGBA build | Restored revision | Restart revision | Evidence |
| --- | --- | ---: | ---: | --- |
| Headless | `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` | 3 | 4 | `/tmp/aw2-mcp-checkpoint-live16/test_live_mcp_checkpoint_resta0/evidence.json` (SHA-256 `ecc199729f21afb4b11c015f1f52a49ea4f938bc60c014edbb82fd1fcbb94ef8`) |
| Windowed | `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810` | 3 | 4 | `/tmp/aw2-mcp-checkpoint-live-windowed2/test_live_mcp_checkpoint_resta0/evidence.json` (SHA-256 `f8fbd3e4f02e50f55b2597026ba7d34df2f71eb842b1d307bf12b8738896d156`) |

These artifacts are outside Git. Each evidence file contains a full serialized
state resource; sibling temporary storage contains generated credentials and
server logs and should be treated as private test data.

## Limits and failures

These runs use deterministic drivers, not a third-party or model-based host.
The MCP-specific gameplay flow does not yet cover `move_attack`; checkpoint,
restart, and resource acceptance is documented above.
Separately, the SDK-vs-SDK live scenario passed in both modes, including attack,
full capture, checkpoint restore/restart, natural HQ victory, and the
revision-matched victory screenshot. Its evidence is under
`/tmp/aw2-sdk-live-final/`; both `evidence.json` files record `passed: true` and
HQ victory at revision 39 (headless frame 10897; windowed frame 10329). The
initial SDK run had reached victory but exposed an artifact-writer bug because
the test treated `ScreenshotObservation` as raw bytes. The writer was corrected
to save its `.png` field and record revision/frame, then the full two-mode
scenario passed.

An attempted longer MCP tank route rolled back with `recovery_required` after
the navigation wall-clock watchdog expired while selecting the unit. The passing
MCP scenario stops after the verified capture instead of claiming that route
passed. A live `wait_for_command` MCP call still remained open after its
gameplay command completed, so the gameplay driver polls `get_command`.
`wait_for_turn`'s bounded timeout passed, but live `wait_for_command` recovery
remains unresolved. Resource notifications and reconnect were verified with
deterministic clients; real model-host behavior remains unverified.
