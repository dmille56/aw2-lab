# AW2 Lab

Initial Python backend scaffold for the emulator-backed AW2 platform.

## Development

Enter the Nix development shell and start the local API:

```sh
nix develop
python -m aw2_lab
```

Install the Git hook once with `pre-commit install`. The hook runs Ruff linting with autofixes, Ruff formatting, and the pytest suite. Run the same checks manually with `ruff check --fix .`, `ruff format .`, and `pytest`.

The server binds to `127.0.0.1:43127` by default. `GET /health` confirms the HTTP process is responsive; it does not indicate that an emulator or match is running. FastAPI's interactive API docs are available at `/docs`.

`nix shell` provides the packaged application, Python, Lua, and mGBA. `nix develop` also includes Ruff, pytest, and pre-commit.
