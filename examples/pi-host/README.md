# Local Pi host for AW2 acceptance

Requires the installed Pi 1.5.0 with built-in MCP support and an existing Pi
provider login. No Pi extension installation is required. The launcher creates
an ignored local directory per match and slot under `.local/aw2-pi/`, with its
own MCP config and session history. Only the AW2 MCP tools are enabled; coding
tools, unrelated extensions, skills, and repository context discovery are disabled.
The built-in MCP extension is explicitly enabled with `--extension builtin:mcp`
alongside `--no-extensions`; Pi 1.5.0 otherwise disables MCP with other extensions.

The local agent directory links your existing Pi `auth.json` and optional
`models.json` to reuse provider login and custom model definitions. Provider
login/refresh state is shared; player credentials and model session histories
are separate. The launcher never changes global MCP settings. Your installed
`pi` command may itself be a user wrapper that updates global Pi settings;
`--pi-bin /path/to/unwrapped/pi` bypasses that wrapper if needed.

First [start the server and provision the match](../../docs/MCP-INTEGRATION.md).
Supply a private file containing the joined slot's player bearer token, not an
operator credential or invitation. The model receives the match ID and slot;
the transport receives the token through `AW2_PLAYER_TOKEN`. Token contents
are never written into the generated MCP config or prompt.

From the repository root, prepare the local configuration without contacting a
model or server:

```sh
python examples/pi_host.py --match-id MATCH_UUID --slot slot_1 \
  --token-file /private/path/player-1-token --prepare-only
```

Verify MCP authentication and tool discovery without a model call:

```sh
python examples/pi_host.py --match-id MATCH_UUID --slot slot_1 \
  --token-file /private/path/player-1-token --check
```

The launcher first verifies the token's match and player slot through the shared
HTTP identity endpoint, rejecting operator tokens and mismatched slots. The
check must then report the `aw2` server connected and expose its tools. Start Pi:

```sh
python examples/pi_host.py --match-id MATCH_UUID --slot slot_1 \
  --token-file /private/path/player-1-token --model PROVIDER/MODEL
```

Omit `--model` to select a model in Pi. Then ask: "Read capabilities and the
state of your assigned match, confirm your player identity, then play your
turn and wait for the next turn." The launcher opens an interactive host; it
does not issue a model request during configuration or `--check`.

For agent-versus-agent runs, open a second terminal with `--slot slot_2` and
the other player's token file. Each host has separate session history and
player credentials. Both talk to the same server. Use `--url` for a different
loopback port; the endpoint must end in `/mcp`. Restart the launcher with the
same match and slot and use Pi's session picker to resume a saved conversation;
reread state before acting.

Repeat human-versus-agent and agent-versus-agent runs in headless and windowed
emulator modes. Record the Pi version, provider/model, actions, command results,
shared revisions, reconnect outcome, and limitations in the acceptance report.
Local session logs may contain full observations; keep them out of Git.
Configuration setup alone does not satisfy the actual model-host acceptance
task in Milestone 4.

Setup verification (2026-11-08): installed Pi 1.5.0 authenticated and discovered
`get_state`, `wait_for_turn`, and the rest of the AW2 catalog through the actual
mounted Streamable HTTP endpoint using a ROM-independent synthetic match and
player credential. No model request or live gameplay was performed. Regression
checks cover configuration isolation, credential handling, player identity, and
loopback restrictions in `tests/test_pi_host.py`.
