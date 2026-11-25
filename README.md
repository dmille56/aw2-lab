# AW2 Lab

Python backend and game client for the emulator-backed AW2 platform.

## Start a local match

With your local ROM configured (`AW2_ROM_PATH`, and optionally
`AW2_SAVE_PROFILE_PATH` for unlocked maps), run these from `nix shell`:

```sh
aw2-lab play pvp
aw2-lab play ai-vs-player --human-slot 1 --model openai/gpt-6-luna
aw2-lab play ai-vs-ai --model-1 openai/gpt-6-luna --model-2 openai/gpt-6-luna
```

The helper creates a fresh private match, starts its own API and emulator on
available loopback ports, and opens authenticated player tabs or a read-only
watch tab. AI slots use external Pi model hosts, not the cartridge's CPU AI.
AI modes require Pi with built-in MCP support and an existing provider login;
`--model` defaults to your existing Pi provider/model setting. Each AI slot has
its own MCP configuration and conversation history. Provider login files are
shared with Pi in the same way as the [existing host launcher](examples/pi-host/README.md).
`--pi-bin` can select an unwrapped executable if your usual `pi` wrapper changes
global settings. Model calls use your configured provider account.

Use `--map rainy_haven`, `--co-1 lash`, `--co-2 max`, `--income 5000`,
`--day-limit none`, `--weather rain`, `--no-co-powers`, and
`--emulator-mode windowed` to choose supported game settings. Run
`aw2-lab play --help` for all options. Maps requiring unlocks need a suitable
local save profile. AI strategy and provider/model compatibility are host concerns.

Source-tree runs need a production browser build: set `AW2_CLIENT_DIST` or use
`--client-dist /path/to/dist` after building `.#client-web`. The Nix package sets
this path automatically. `--sprite-pack /path/to/extracted/pack` enables your
external game artwork; symbols work without a pack. No ROM or extracted artwork
is packaged or copied into the repository.

The launcher checks that the selected browser build supports automatic connection
before creating a match. If an older Nix shell loads current Python source via
`PYTHONPATH` but still uses an old `prototypes/client/dist` symlink, rebuild it:

```sh
nix build .#client-web --out-link prototypes/client/dist
```

Then start the launcher again. A fresh `nix shell` also supplies the current
packaged browser build. A running server keeps the build selected at startup;
rebuilding affects new launches. Stopping and starting this helper creates a new
match, while the previous match's checkpoints remain in its private run directory.

`--no-browser` writes private launch links to the printed run directory's
`views.json`. Links are one use and expire after five minutes; their fragment is
removed before exchanging it for a player credential. Credentials remain in
page memory, so reloading requires connecting again with the appropriate private
`slot_1.token`, `slot_2.token`, or `watch.token` file. Watch access is enforced
read-only by the server. Do not share these files or launch links.

The match helper currently targets Linux/NixOS.

Press Ctrl-C to stop the helper's server, emulator, and AI subprocesses. Data is
retained under `$XDG_STATE_HOME/aw2-lab/play/` (normally
`~/.local/state/aw2-lab/play/`), including checkpoints, private tokens, and AI logs.
`--run-dir` selects a new private directory; existing directories are rejected
rather than resetting a saved match. This command starts new matches; it does
not resume existing runs or attach to another running server. Existing games
and their processes are untouched. `--max-ai-turns N` bounds AI execution for
short checks; `--ai-turn-timeout` bounds each host invocation. A failed host or
an unfinished turn stops the helper with the private log path instead of silently
repeating actions or model calls.

Add `--ai-log` to an AI match to follow tool calls, outcomes, and durations
in the launcher's terminal. Each event line identifies the AI player, game
day, turn, and retry attempt. A turn summary shows total elapsed time and
the combined tool and estimated thinking durations across attempts. Use
`--ai-log details` to include bounded tool arguments, results, thinking
durations, and thinking text when the model provider exposes it to Pi.
Event durations are estimated from when the follower reads the Pi log.
Terminal prefixes are colored by player. Set `NO_COLOR` for plain text.
Redirected output is always plain.
Both modes keep the full private `slot_N/turn-N.jsonl` log in the run directory
for later inspection.


## Launch the client prototype

The React client supports board inspection and gameplay through the local API.
Use the match helper above for automatic setup, or launch the prototype server
for manual setup and existing API workflows.
Run these commands from the repository root on Nix/NixOS.

In one terminal, start the prototype server with your own supported AW2 ROM
stored outside the repository:

```sh
nix shell
PYTHONPATH="$PWD/src" python prototypes/client/serve.py --rom-path /path/to/aw2.gba
```

Alternatively, set `AW2_ROM_PATH` and omit `--rom-path`:

```sh
export AW2_ROM_PATH=/path/to/aw2.gba
PYTHONPATH="$PWD/src" python prototypes/client/serve.py
```

An explicit `--rom-path` takes precedence over `AW2_ROM_PATH`.

This starts the API and headless mGBA, serves the browser client, and enables the
native prototype's HTTP origin. Stop any existing AW2 Lab server first: the
prototype uses API port 43127 and bridge port 43128. Use this helper for the
client checks below; the normal server command does not serve the prototype.

For the **browser client**, open
[http://127.0.0.1:43127/client/](http://127.0.0.1:43127/client/).

For the **Linux desktop client**, open a second terminal in the repository root
and launch it in your graphical session:

```sh
nix shell
aw2-client-prototype
```

Both clients should display `Connected` and a health response with
`"emulator": "running"`. Use **Check connection** to retry. Close the desktop
window to stop that client; press Ctrl+C in the server terminal to stop the API
and its emulator.

The normal `nix shell` provides both the desktop client and Python with the
server's runtime dependencies. Re-enter it after updating the flake to pick up
the client command. `PYTHONPATH` above selects the server code from your checkout.

The default development shell also includes `aw2-client-prototype`, including
when loaded through lorri. After updating `.envrc`, run `direnv allow` and let
lorri rebuild the environment. If you need a fresh lorri shell immediately, run
`lorri shell --flake .`, then `aw2-client-prototype`.

See the [prototype instructions](prototypes/client/README.md) for the client
development shell, X11/Wayland smoke checks, and current compatibility limits.

## Development

Enter the Nix development shell and start the local API:

```sh
nix develop
python -m aw2_lab --rom /path/to/aw2.gba
```

The development environment includes `python-lsp-server` (`pylsp`) for editor integration. Install the Git hook once with `pre-commit install`. The hook runs Ruff linting with autofixes, Ruff formatting, Luacheck, Lua syntax checks, the Busted Lua bridge suite, mypy, and pytest. Run the Lua suite directly with `busted tests/lua`.

For ROM-independent checks, optional emulator integration checks, ROM/checkpoint handling, and verified-scope limits, see the [verification workflow](docs/VERIFICATION.md).

The server binds to `127.0.0.1:43127` by default. `GET /health` reports HTTP responsiveness and whether the managed mGBA process is running; it does not indicate that the Lua bridge or a match is ready. FastAPI's interactive API docs are available at `/docs`. The MCP server is available over Streamable HTTP at `/mcp` in the same process and exposes [typed lifecycle, gameplay, command, and checkpoint tools](docs/MCP-TOOLS.md) backed by the shared SDK and HTTP API. It requires a provisioned operator or claimed-player bearer credential; see [local MCP authorization](docs/MCP-AUTHORIZATION.md). MCP access is limited to loopback peers.

Starting the server requires your own legally obtained AW2 ROM. Provide it with `--rom /path/to/aw2.gba` or set `AW2_ROM_PATH=/path/to/aw2.gba`; the CLI option takes precedence, and the path must point to a file. To start with an unlocked profile, provide `--save-profile /path/to/all-unlocked.sps` or set `AW2_SAVE_PROFILE_PATH` to that `.sps` (an mGBA `.sav` is also accepted). The launcher checks the `.sps` against the configured ROM, converts it to a temporary `.sav`, and runs from a temporary ROM/save pair; it does not write to the `.sps`, adjacent saves, or the original ROM. The temporary save is discarded when the emulator stops, so each startup begins with the supplied profile. Select the emulator frontend with `--emulator-mode headless|windowed` or `AW2_EMULATOR_MODE=headless|windowed`; the CLI option takes precedence and the default is `headless`. The default executables are `mgba-headless` for headless and `mgba-qt` for windowed. Override them with `--mgba-headless PATH` or `--mgba-windowed PATH`. The launcher passes the bundled Lua bridge using mGBA's `--script` startup option; override the script with `--lua-bridge PATH`. The Nix environment supplies both frontends from a pinned upstream 0.11 development revision with Lua scripting enabled. The server starts mGBA when it starts and stops it when the server shuts down. ROMs are not included with the project; keep them outside the repository and the Nix store.

`nix shell` provides the packaged application, the desktop client prototype, Python with server runtime dependencies, Lua, Busted, mGBA, and mypy. `nix develop` also includes Ruff, pytest, pre-commit, mypy, and `pylsp`.

The mGBA source is pinned in `flake.nix` and `flake.lock` to upstream commit
[`fd9dc5c2cbf234365068855851107e762fc6211b`](https://github.com/mgba-emu/mgba/commit/fd9dc5c2cbf234365068855851107e762fc6211b).
The build explicitly enables the headless and Qt frontends, Lua 5.2, and scripting.
Package checks verify that both frontends advertise `--script`. The SDL frontend
(`mgba`) is not built; it is a windowed frontend and is unsuitable for headless mode.
The Qt frontend has a small patch that loads startup scripts without opening the
graphical scripting console by default. In windowed mode, use
`--scripting-console` or set `AW2_MGBA_SCRIPTING_CONSOLE=true` to open it at
startup; the setting defaults to false. The CLI option takes precedence, and
`--no-scripting-console` disables it even when the environment variable is true.
The console also remains available from mGBA's Tools menu for manual debugging.

The launcher sets `AW2_MGBA_FRAME_GATE=1` to enable the patch in
`nix/patches/mgba-frame-gate.patch`. Both frontends start paused and poll the
bridge every 5 ms without executing gameplay. Lua queues a budget through the
patch's `emu:requestFrames` method; native code runs it after the Lua callback
returns, then invokes `bridgeComplete` to send the result. Polling from ordinary
frame callbacks requires gameplay to run, and running the core recursively from
Lua callbacks hung the pinned build during integration checks. This patch keeps
idle requests responsive and bounds execution to explicit server requests.
In windowed mode, local controller input, resume, and frame-step controls are
ignored while gated. Audio/video synchronization waits are disabled so a frame
budget can complete while the window is paused. Running either patched frontend
without `AW2_MGBA_FRAME_GATE=1` retains its normal behavior.

Build the emulator separately with `nix build .#mgba`. After changing the flake,
enter a fresh `nix shell` or `nix develop` so the new executables are on PATH.
For example:

```sh
nix shell
aw2-lab --rom /path/to/aw2.gba --emulator-mode headless
```

The launcher waits for a versioned bridge handshake before the API server starts
serving. A missing bridge, unsupported handshake, or mGBA startup failure aborts
startup with a diagnostic. `LuaBridgeClient.read_memory_batch()` reads up to 64
ranges (4096 combined bytes) in one paused bridge callback. `save_state(path)`
and `load_state(path)` use mGBA's full state flags, including save RAM; keep
these build-specific state files outside the repository and Nix store.
`save_state_buffer()` and `load_state_buffer(bytes)` support in-memory
checkpoints up to 3 MiB. `reset()` releases all keys before resetting.
Startup was verified locally with an AW2 ROM on 2026-10-20 through both
`python -m aw2_lab` and the packaged `aw2-lab` command. Both emulator modes
reported a running emulator through `/health`, loaded the bridge automatically,
answered repeated Python connections, and returned ROM-header memory matching
the loaded file. Headless startup ran with display variables unset; windowed
startup produced exactly one mapped game window on the X display, without a
scripting console with the default setting. Server shutdown stopped each
emulator and released the bridge port. These checks used temporary configuration
and save directories outside the repository.

The bridge supports direct key-mask control with `LuaBridgeClient.set_keys(mask)`;
`set_keys(0)` releases every button. `press_keys(mask, frames)` applies the mask
for the requested number of emulated frames and releases it before returning.
Masks use mGBA's GBA key bit positions (`A=0`, `B=1`, `SELECT=2`, `START=3`,
`RIGHT=4`, `LEFT=5`, `UP=6`, `DOWN=7`, `R=8`, `L=9`). For example, mask `1`
holds A. A press is capped at 600 frames, matching bounded frame advancement.
On 2026-10-20, a live headless check held A for three frames: mGBA reported a
frame transition from 18574 to 18577 and confirmed that all keys were released.
On 2026-10-21, the same three-frame A press passed in windowed mode, from frame
259 to 262, with the bridge confirming release.

`LuaBridgeClient.advance_frames(count)` advances exactly 0–600 frames and returns
the ending frame number. Passing zero queries the current frame without running
the core. Held masks from `set_keys` persist across advances; `press_keys` replaces
the mask for its budget and then releases all keys. Frame counts are checked
against the emulator's counter, including its 32-bit wraparound.

ROM-independent bridge and launcher checks run by default. To run the frame gate
integration checks against your local ROM in both frontends:

```sh
nix develop
AW2_RUN_EMULATOR_TESTS=1 AW2_ROM_PATH=/path/to/aw2.gba \
  pytest tests/test_frame_gate_integration.py -v
```

Stop an existing AW2 Lab emulator first; the checks require bridge port 43128.
They use temporary configuration, save, and checkpoint directories, verify
bridge readiness, idle queries, coherent batched reads, state save/restore,
exact budgets through 600 frames, key presses and release, and shutdown.
Windowed mode requires a display; with X11 and `xdotool` available,
the checks also verify that resume and frame-step shortcuts leave the core idle.
Set `AW2_TEST_MGBA_HEADLESS` or `AW2_TEST_MGBA_WINDOWED` to test specific emulator
executables.

On 2026-10-21, live frame gate checks passed in both modes: startup remained at
frame 0, idle queries and memory reads left it unchanged, and explicit budgets
of 1, 3, 17, and 600 frames advanced exactly. After the held-input and press
checks, both modes stayed idle at frame 627. The X11 window's resume and
frame-step shortcuts also left the game paused. Follow-up checks in both modes
verified batched reads, save/restore of full state and save RAM flags, and reset.

Operator credentials and the shared match authorization service are configured
through `--operator-secret-file` or `AW2_OPERATOR_SECRET_FILE`. See
[authorization setup](docs/AUTHORIZATION.md) for provisioning, retry/revocation
semantics, and current transport limitations.

## AW2 Links
- https://strategywiki.org/wiki/Advance_Wars_2:_Black_Hole_Rising
- https://www.warsworldnews.com/wp/aw2/maps-aw2/advance-wars-2-maps/
