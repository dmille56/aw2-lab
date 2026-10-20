# AW2 Lab

Initial Python backend scaffold for the emulator-backed AW2 platform.

## Development

Enter the Nix development shell and start the local API:

```sh
nix develop
python -m aw2_lab --rom /path/to/aw2.gba
```

The development environment includes `python-lsp-server` (`pylsp`) for editor integration. Install the Git hook once with `pre-commit install`. The hook runs Ruff linting with autofixes, Ruff formatting, mypy, and the pytest suite. Run the same checks manually with `ruff check --fix .`, `ruff format .`, `mypy`, and `pytest`.

The server binds to `127.0.0.1:43127` by default. `GET /health` reports HTTP responsiveness and whether the managed mGBA process is running; it does not indicate that the Lua bridge or a match is ready. FastAPI's interactive API docs are available at `/docs`. The MCP server is available over Streamable HTTP at `/mcp` in the same process and currently exposes a `hello_world` tool.

Starting the server requires your own legally obtained AW2 ROM. Provide it with `--rom /path/to/aw2.gba` or set `AW2_ROM_PATH=/path/to/aw2.gba`; the CLI option takes precedence, and the path must point to a file. Select the emulator frontend with `--emulator-mode headless|windowed` or `AW2_EMULATOR_MODE=headless|windowed`; the CLI option takes precedence and the default is `headless`. The default executables are `mgba` for headless and `mgba-qt` for windowed. Override them with `--mgba-headless PATH` or `--mgba-windowed PATH`. The server starts mGBA when it starts and stops it when the server shuts down. ROMs are not included with the project; keep them outside the repository and the Nix store.

`nix shell` provides the packaged application, Python, Lua, mGBA, and mypy. `nix develop` also includes Ruff, pytest, pre-commit, mypy, and `pylsp`.
