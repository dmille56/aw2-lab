# AW2 Lab

Initial Python backend scaffold for the emulator-backed AW2 platform.

## Development

Enter the Nix development shell and start the local API:

```sh
nix develop
python -m aw2_lab
```

The development environment includes `python-lsp-server` (`pylsp`) for editor integration. Install the Git hook once with `pre-commit install`. The hook runs Ruff linting with autofixes, Ruff formatting, mypy, and the pytest suite. Run the same checks manually with `ruff check --fix .`, `ruff format .`, `mypy`, and `pytest`.

The server binds to `127.0.0.1:43127` by default. `GET /health` confirms the HTTP process is responsive; it does not indicate that an emulator or match is running. FastAPI's interactive API docs are available at `/docs`. The MCP server is available over Streamable HTTP at `/mcp` in the same process and currently exposes a `hello_world` tool.

When emulator startup is available, provide your own legally obtained AW2 ROM with `--rom /path/to/aw2.gba` or set `AW2_ROM_PATH=/path/to/aw2.gba`. The command-line option takes precedence. The path is optional while emulator startup is not configured, and any supplied path must point to a file. ROMs are not included with the project; keep them outside the repository and the Nix store.

`nix shell` provides the packaged application, Python, Lua, mGBA, and mypy. `nix develop` also includes Ruff, pytest, pre-commit, mypy, and `pylsp`.
