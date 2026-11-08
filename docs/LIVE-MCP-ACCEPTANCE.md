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

## Limits and failures

These runs use a deterministic driver, not a third-party or model-based host.
The MCP-specific flow does not yet cover `move_attack`, checkpoint export/import
and restore, server restart/resume, or live resource subscription/reconnect.
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
passed. A direct live `wait_for_command` MCP call also remained open after the
underlying command completed, so this acceptance driver polls `get_command`;
bounded host waiting still needs live verification.
