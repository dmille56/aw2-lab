# Human client prototype

This checks the proposed [client architecture](../../docs/CLIENT-ARCHITECTURE.md).
It shares browser assets with Tauri 2 and includes an initial read-only match
viewer: selectable terrain and unit tiles, an inspector and roster, player funds
and observed CO power data, snapshot import/export, HTTP SSE updates, and
revision-matched screenshots. The existing health check and native smoke reporting
remain available. Gameplay controls and a visual power meter with verified charge
thresholds are pending. It does not execute gameplay commands or bundle the server. Cargo.lock pins the
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
origins to perform reads with an Authorization header, including preflight. These origins are a prototype configuration; the normal
server's CORS policy is unchanged. No ROM paths or contents enter the Nix build.

Open that URL in a browser, or run the packaged client:

```sh
./result/bin/aw2-client-prototype
```

Keep the API helper running in another terminal while using live inspection.
The native client does not start the server. With the API stopped, the viewer
still opens for snapshot inspection and shows a server connection error.

The Linux package defaults `WEBKIT_DISABLE_DMABUF_RENDERER=1` to avoid the
reproduced black window and `Failed to create GBM buffer` errors on the primary
display. This uses WebKitGTK's alternate rendering path; it does not disable the
webview sandbox. See [Tauri's graphics guidance](https://v2.tauri.app/develop/debug/linux-graphics/).
If your driver supports the faster DMA-BUF path, you can explicitly opt back in:

```sh
WEBKIT_DISABLE_DMABUF_RENDERER=0 ./result/bin/aw2-client-prototype
```

For an unwrapped `cargo run`, apply the workaround in the launching shell when
needed: `WEBKIT_DISABLE_DMABUF_RENDERER=1 cargo run --locked --manifest-path prototypes/client/Cargo.toml`.

Alternatively, enter the normal `nix shell` in a second terminal and run
`aw2-client-prototype`. It includes both the desktop client and Python with the
server runtime dependencies. Re-enter the shell after updating the flake to pick
up the client command. Setting `PYTHONPATH` in the helper command selects the
checkout's Python package. For a shell containing only the native client, use
`nix shell .#client-prototype`.

The default development shell used by lorri also includes the client. After an
`.envrc` update, run `direnv allow` and wait for lorri to rebuild, or enter a fresh
shell with `lorri shell --flake .`. Then run `aw2-client-prototype` directly.
The lorri shell also selects the development Python environment, including
`uvicorn` and the API dependencies, so the helper can run directly without an
additional `nix shell`. After a shell update, let lorri finish rebuilding and run
`direnv reload` (or leave and re-enter the directory) to refresh an existing
terminal. Check it with `python -c 'import uvicorn; print(uvicorn.__version__)'`.

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
server selection, mobile HTTPS, gameplay controls, generated TypeScript schemas, and production frontend tooling
remain follow-up work. Native platforms other than Linux require their own
shell scaffolding, SDKs, signing and runtime evidence.

## Inspect a match or snapshot

For authenticated match inspection, use the operator credential and storage
directory used to provision the match:

```sh
PYTHONPATH="$PWD/src" python prototypes/client/serve.py \
  --rom-path /path/to/aw2.gba \
  --operator-secret-file ~/.config/aw2-lab/operator-token \
  --storage-dir /path/to/your/aw2-storage \
  --emulator-mode headless
```

Use `windowed` to watch the emulator too. Provision and start the match using
[the HTTP/SDK setup flow](../../docs/HTTP-API.md). At `/client/`, enter the match
ID and that player's credential, not the operator credential. Credentials stay in
page memory and are cleared on disconnect or authorization loss. Reloading the
page requires reconnecting.

`Open snapshot` accepts an exported versioned `StateResponse` JSON document.
`Export snapshot` saves the displayed state without the connection credential.
The bundled native viewer can inspect snapshots with the server stopped; the
browser page must first be served by the helper. See
[the client design](../../docs/HUMAN-CLIENT-DESIGN.md) for the remaining action controls.

The readable terrain/unit catalog is generated from shared Python rule data.
After changing those rules, regenerate it with:

```sh
PYTHONPATH="$PWD/src" python prototypes/client/generate_catalog.py
```

The test suite checks the generated file for drift. These baseline facts are
shown separately from observations and may differ from current CO modifiers.
