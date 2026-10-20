# AW2 Lab

Initial Python backend scaffold for the emulator-backed AW2 platform.

## Development

Enter the Nix development shell and start the local API:

```sh
nix develop
aw2-lab
```

The server binds to `127.0.0.1:43127` by default. `GET /health` confirms the HTTP process is responsive; it does not indicate that an emulator or match is running. FastAPI's interactive API docs are available at `/docs`.

`nix shell` provides the packaged application and the same Python dependencies, Lua, and mGBA.
