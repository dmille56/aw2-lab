# Human client prototype

This checks the proposed [client architecture](../../docs/CLIENT-ARCHITECTURE.md).
It shares browser assets with Tauri 2 and includes an initial read-only match
viewer: selectable terrain and unit tiles, an inspector and roster, player funds
and observed CO power data, snapshot import/export, HTTP SSE updates, and
revision-matched screenshots. The existing health check and native smoke reporting
remain available. Gameplay controls and a visual power meter with verified charge
thresholds are pending. It does not execute gameplay commands or bundle the server. Cargo.lock pins the
native dependencies; `package-lock.json` pins React, TypeScript, Vite, and the
quality tools. React renders the viewer; Vite builds one shared production asset
directory for the browser and native shell. The small solid-color PNG is a placeholder required by Tauri.

From the repository root, build the packaged native client:

```sh
nix build .#client-prototype
```

Build the same production assets for the browser helper (repeat after frontend changes):

```sh
nix build .#client-web --out-link prototypes/client/dist
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
asset changes. The browser helper serves `prototypes/client/dist`, never raw
TypeScript. You can also set `AW2_CLIENT_DIST` to an existing production build
directory. The Nix desktop package embeds that same Vite build; Node is a build
dependency, not a native runtime requirement.

Only the default loopback address/port is supported by this prototype. Production
server selection, mobile HTTPS, and gameplay controls remain follow-up work. Native platforms other than Linux require their own
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

## Automated quality gates

From the repository root, run the fast checks used by pre-commit:

```sh
nix run .#check-client -- --fast
```

Run the full client gate before completing client work:

```sh
nix run .#check-client
```

The normal Nix/lorri development environment also provides `aw2-client-check`
with the same arguments. No local `npm install` or browser download is required
for these commands. The tool copies the current prototype into a temporary
workspace and links locked Nix-provided tool packages there; it checks current
uncommitted edits without modifying source files or installing dependencies into
the checkout. A changed package lock requires rebuilding/re-entering the shell.

| Gate                                                                              | Fast/pre-commit | Full/local |
| --------------------------------------------------------------------------------- | --------------- | ---------- |
| Typed ESLint/React Hooks, Prettier, CSS Stylelint, HTML validation                | Yes             | Yes        |
| Tauri JSON schema and npm lock consistency                                        | Yes             | Yes        |
| Vitest validation/session/component tests and V8 coverage report                  | Yes             | Yes        |
| Python Ruff, strict mypy (including fixture helpers), focused pytest              | Yes             | Yes        |
| Strict TypeScript and Vite production build                                       | Yes             | Yes        |
| Rust `cargo fmt --check`                                                          | Yes             | Yes        |
| Catalog/API-schema/type/validator drift and fixture compatibility                 | Yes             | Yes        |
| Playwright behavior, keyboard navigation, axe accessibility and visual regression |                 | Yes        |
| Packaged Tauri build, Clippy with denied warnings, locked Cargo tests             |                 | Yes        |
| Packaged X11 native health success/failure under Xvfb                             |                 | Yes        |

The existing repository Nix formatting/static checks and all Python/Lua hooks
remain part of `pre-commit run --all-files`. Checks run locally through pre-commit;
run the full client command locally for the heavier browser/native checks.
GitHub Actions testing is deferred. Browser failures retain traces and screenshots under `prototypes/client/test-results/`;
full runs also save focused coverage reports there. Ordinary gates use synthetic
state and never start mGBA or need a ROM. Live emulator tests remain explicitly
opt-in through the existing integration-test commands.

The full gate needs ports **43979** (browser fixture) and **43127** (native health
fixture) free; stop the real API first. The native check verifies its own fixture
identity and never treats a connection to an existing game server as a pass.
Xvfb checks establish native startup and HTTP behavior, not full native rendering,
file dialogs, Wayland, or other-platform acceptance. Those remain milestone tasks.

Visual baselines use the pinned Nix Chromium and fonts. Review changes rather than
updating baselines automatically. To intentionally record new baselines:

```sh
nix run .#check-client -- --update-snapshots
```

Review and commit the resulting PNG changes in `tests/browser/*-snapshots/`, then
run the full gate without that flag. Coverage measures handwritten TypeScript/React
modules, including the session layer and components; generated code and the entry
point are excluded. Browser tests cover the integrated production viewer. The
migration preserves the existing visual baseline.

## Frontend development and generated contracts

For an editable npm workspace, enter `nix develop .#client`, then:

```sh
cd prototypes/client
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/health` and `/v1` to the separately
running local API on port 43127, including streaming events. The production
browser helper continues to serve `/client/` from the same origin as the API.
Use `npm run build` before direct `cargo run`; direct Cargo does not invoke
Tauri CLI's `beforeBuildCommand`. The packaged Nix build handles this automatically.

Python's shared v1 models are the schema authority. Both input and output schemas
are exported without constructing an API, accessing credentials, or launching an
emulator. After changing those contracts, regenerate and review the artifacts:

```sh
PYTHONPATH=src python prototypes/client/generate_api.py
cd prototypes/client
npm run generate
```

`schemas/api-v1.json` is an OpenAPI 3.1 components document, not an endpoint catalog.
`web/generated/api.ts` supplies types for API input/output models; handwritten UI
modules import those types. `web/generated/validate-state.js` validates incoming
state against that schema, followed by boundary and resource-limit checks. The
validator is generated ahead of time rather than compiling schemas in the webview,
so Tauri needs no `unsafe-eval` CSP exception. UUID identity is checked at the
client boundary; date-time format semantics remain server validation. Both Python
schema drift and Node-generated type/validator drift fail the local quality gate.

`package-lock.json` pins the frontend development tools. Playwright's npm version
must equal the version in the locked nixpkgs package set; the flake rejects a
mismatch. When updating dependencies, regenerate the lock and update `npmDepsHash`
in `nix/client-checks.nix` using `prefetch-npm-deps`. The minimatch override pins
11.0.1 until ESLint's dependency range includes the patched release; see
[the upstream advisory](https://github.com/advisories/GHSA-g3hv-75wg-m249).

The official Tauri schema is vendored in `schemas/tauri-config.schema.json` so
validation is offline. Its `$id` must match the Tauri version in `Cargo.lock`;
refresh it from `https://schema.tauri.app/config/2` when updating Tauri and review
the schema change. Generated catalog and vendored schema files are verified
separately from source formatting/linting.
