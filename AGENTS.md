# Repository Guidelines

## Project Structure & Module Organization

The Python package lives in `src/aw2_lab/`. Keep the CLI in `cli.py`, the HTTP boundary in `api/`, and place future emulator, bridge, state, match, SDK, and MCP code in separate modules as the architecture grows. Tests live in `tests/`; use `test_*.py` filenames. `PLAN.md` describes planned behavior and integration milestones. `flake.nix` defines the Nix package and development environments.

## Build, Test, and Development Commands

- Prefer `nix shell` as the normal project environment; it provides the packaged app, Python, Lua, mGBA, and pre-commit. Use `nix develop` when you specifically need its development shell setup, including Ruff and pytest.
- `python -m aw2_lab` starts the local API on `127.0.0.1:43127`; override with `--host` or `--port`.
- `pytest` runs the test suite; `nix build` builds the default package and runs its package checks.
- `ruff check --fix .` lints and applies safe fixes; `ruff format .` formats Python files.
- `pre-commit install` enables repository hooks; `pre-commit run --all-files` runs them manually.

When adding new files, add them to Git before relying on a local flake build: Nix’s Git flake source omits untracked files.

## Coding Style & Naming Conventions

Use four spaces for Python indentation, descriptive `snake_case` names for modules, functions, and variables, and `PascalCase` for classes. Ruff settings in `pyproject.toml` are authoritative (100-character lines, Python 3.14 target). Keep HTTP concerns separate from emulator transport and game-state logic. Prefer typed interfaces at module boundaries.

## Testing Guidelines

Use pytest and name tests `test_*.py`; place them under `tests/`. Cover observable behavior and error paths when adding functionality. Before considering any task complete, run `pre-commit run --all-files` and require every hook to pass. If this cannot proceed because a required binary or library is missing, retry with `nix develop -c pre-commit run --all-files`. If a hook reports a code failure, fix it and rerun the full command; report any blocker instead of marking the task done. Emulator integration tests should be clearly separated from ROM-independent checks and must not require a ROM by default.

## Commit & Pull Request Guidelines

Recent commits use short, lowercase imperative or action-oriented summaries (for example, `add initial flake.nix`). Keep commits focused. Pull requests should explain the change, list relevant checks and their results, link related issues when applicable, and include screenshots only for visual changes. Call out behavior that remains planned or unverified against mGBA.

## Security & Local Configuration

The API binds to loopback by default. Keep ROMs, save states, credentials, and machine-specific paths out of Git and the Nix store. Do not add secrets to flakes, tests, or documentation.
