# Client compatibility prototype

This checks the proposed [client architecture](../../docs/CLIENT-ARCHITECTURE.md).
It embeds static browser assets in Tauri 2 and reads the real API's `/health`.
It does not execute gameplay commands or bundle the server. Cargo.lock pins the
native dependencies; the prototype has no npm dependencies or build-time network
assets. The small solid-color PNG is a placeholder required by Tauri.

From the repository root, build the packaged native client:

```sh
nix build .#client-prototype
```

Run the prototype API with an external supported ROM (close any other server
using ports 43127/43128 first):

```sh
nix shell
PYTHONPATH="$PWD/src" python prototypes/client/serve.py --rom-path /path/to/aw2.gba
```

The helper also accepts `AW2_ROM_PATH`, like the main server. Set it in your
shell and omit `--rom-path`; an explicit CLI path takes precedence:

```sh
export AW2_ROM_PATH=/path/to/aw2.gba
PYTHONPATH="$PWD/src" python prototypes/client/serve.py
```

Paths expand `~` and must refer to a file. The server still verifies the ROM
checksum before launching mGBA.

The helper runs the existing application and headless emulator, serves the page
at `http://127.0.0.1:43127/client/`, and allows only the explicit native Tauri
origins to read health. These origins are a prototype configuration; the normal
server's CORS policy is unchanged. No ROM paths or contents enter the Nix build.

Open that URL in a browser, or run the packaged client:

```sh
./result/bin/aw2-client-prototype
```

Alternatively, enter the normal `nix shell` in a second terminal and run
`aw2-client-prototype`. It includes both the desktop client and Python with the
server runtime dependencies. Re-enter the shell after updating the flake to pick
up the client command. Setting `PYTHONPATH` in the helper command selects the
checkout's Python package. For a shell containing only the native client, use
`nix shell .#client-prototype`.

The default development shell used by lorri also includes the client. After an
`.envrc` update, run `direnv allow` and wait for lorri to rebuild, or enter a fresh
shell with `lorri shell --flake .`. Then run `aw2-client-prototype` directly.

Check both the successful response and a visible connection failure with the
server stopped. The request times out after five seconds. The native smoke mode
prints the page's result and exits zero on success or one on failure; use an
outer timeout to catch a webview that never starts:

```sh
AW2_CLIENT_SMOKE_TEST=1 GDK_BACKEND=x11 timeout 20s ./result/bin/aw2-client-prototype
AW2_CLIENT_SMOKE_TEST=1 GDK_BACKEND=wayland timeout 20s ./result/bin/aw2-client-prototype
```

Run the second command in an actual Wayland session or with a temporary headless
Weston compositor and its `WAYLAND_DISPLAY` socket configured. A Wayland pass
under a nested compositor is evidence of native backend startup, not a check of
every desktop, GPU, or display scaling configuration. Keep platform-specific
failures in the evidence record; do not disable WebKit's sandbox to obtain a pass.

The separate `nix develop .#client` shell provides Rust, Cargo, rustfmt, Node,
TypeScript, pkg-config, and GTK/WebKit development libraries. For iterative native
work run `cargo run --locked --manifest-path prototypes/client/Cargo.toml` in that
shell. Use the wrapped Nix package for runtime acceptance. Rebuild it after any
asset changes; the browser helper serves assets directly from the checkout.

Only the default loopback address/port is supported by this prototype. Production
server selection, mobile HTTPS, authenticated transport, schemas and gameplay UI
remain follow-up work. Native platforms other than Linux require their own
shell scaffolding, SDKs, signing and runtime evidence.
