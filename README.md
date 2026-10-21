# AW2 Lab

Initial Python backend scaffold for the emulator-backed AW2 platform.

## Development

Enter the Nix development shell and start the local API:

```sh
nix develop
python -m aw2_lab --rom /path/to/aw2.gba
```

The development environment includes `python-lsp-server` (`pylsp`) for editor integration. Install the Git hook once with `pre-commit install`. The hook runs Ruff linting with autofixes, Ruff formatting, Luacheck, Lua syntax checks, the Busted Lua bridge suite, mypy, and pytest. Run the Lua suite directly with `busted tests/lua`.

The server binds to `127.0.0.1:43127` by default. `GET /health` reports HTTP responsiveness and whether the managed mGBA process is running; it does not indicate that the Lua bridge or a match is ready. FastAPI's interactive API docs are available at `/docs`. The MCP server is available over Streamable HTTP at `/mcp` in the same process and currently exposes a `hello_world` tool.

Starting the server requires your own legally obtained AW2 ROM. Provide it with `--rom /path/to/aw2.gba` or set `AW2_ROM_PATH=/path/to/aw2.gba`; the CLI option takes precedence, and the path must point to a file. Select the emulator frontend with `--emulator-mode headless|windowed` or `AW2_EMULATOR_MODE=headless|windowed`; the CLI option takes precedence and the default is `headless`. The default executables are `mgba-headless` for headless and `mgba-qt` for windowed. Override them with `--mgba-headless PATH` or `--mgba-windowed PATH`. The launcher passes the bundled Lua bridge using mGBA's `--script` startup option; override the script with `--lua-bridge PATH`. The Nix environment supplies both frontends from a pinned upstream 0.11 development revision with Lua scripting enabled. The server starts mGBA when it starts and stops it when the server shuts down. ROMs are not included with the project; keep them outside the repository and the Nix store.

`nix shell` provides the packaged application, Python, Lua, Busted, mGBA, and mypy. `nix develop` also includes Ruff, pytest, pre-commit, mypy, and `pylsp`.

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
these build-specific state files outside the repository and Nix store. The
bridge also provides `reset()`, which releases all keys before resetting.
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
