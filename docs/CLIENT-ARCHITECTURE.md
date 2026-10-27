# ADR 001: shared web client with Tauri native shells

Status: accepted for Milestone 3 architecture and the verified NixOS prototype.
Other platform support remains unverified.

## Context and decision

Nix/NixOS is the primary development and verification environment. Milestone 3
ships the Python SDK and two-client examples; it also establishes a client
architecture and small compatibility prototypes before gameplay UI development.

Choose a shared React and TypeScript web client, built with Vite, with Tauri 2
shells for Linux, macOS, Windows, Android, and iOS. React provides the gameplay
UI components and coordinates presentation state for the map, selected units,
menus, and command status. Vite provides development serving and asset builds.
Keep networking, serialized models, and presentation independent of Tauri.
The compatibility prototype uses static HTML/JavaScript to isolate the native
runtime from frontend build tooling. It is not the playable client.

Python runs in the authoritative server and the separate Python SDK for scripts
and agents. UI clients consume HTTP and do not bundle Python, mGBA, ROMs, saves,
or another rules engine. Installing a native client does not install a server.
Mobile loopback refers to the phone, so mobile clients will need a separately
reachable server. Remote hosting, TLS deployment, and public accounts remain
outside the initial local release.

Tauri uses platform webviews and requires Linux system libraries and separate
mobile toolchains. These requirements make a packaged NixOS prototype an
acceptance gate, rather than assuming upstream platform support proves project
compatibility. See [Tauri prerequisites](https://tauri.app/start/prerequisites/)
and [distribution guidance](https://tauri.app/distribute/).

## Alternatives and maintenance

| Candidate | Coverage and benefits | Costs and decision |
| --- | --- | --- |
| React/TypeScript + Vite + Tauri 2 | Shared browser UI and desktop/mobile shells; native code can stay small | React dependencies plus Rust, platform webviews, native signing and differing browser behavior; selected with prototype evidence limited to the native runtime and HTTP transport |
| Browser/PWA only | One deployment, no native build pipeline | Installation and capabilities vary by browser; does not establish native package support; retain browser delivery as a useful independent target |
| Electron + Capacitor | Shared web UI; Electron supplies its desktop browser engine | Two native integration stacks and desktop browser updates; fallback if Tauri runtime problems outweigh its benefits |
| Flutter | One Dart UI across web, desktop, and mobile | Adds Dart and a separate rendering/toolchain ecosystem; less direct reuse of browser DOM and HTTP tooling |
| Python + Qt | Familiar language and a mature desktop toolkit | Separate browser/mobile approach or additional deployment work; keep Python focused on the server and SDK |

Maintenance includes reviewing React and other Cargo/npm dependency updates, Nix closure changes,
webview regressions, accessibility, mobile lifecycle behavior, and native signing.
Avoid native plugins until a concrete feature needs one. The browser client must
remain usable without native IPC. Electron supports desktop platforms, while
Capacitor targets web/Android/iOS; combining them requires two shell pipelines.
Sources: [Electron](https://github.com/electron/electron),
[Capacitor environment setup](https://capacitorjs.com/docs/getting-started/environment-setup),
[Flutter platforms](https://docs.flutter.dev/reference/supported-platforms),
[PWA installation](https://web.dev/learn/pwa/installation).

## HTTP contract constraints

The public contract is defined in
[MATCH-CONTRACT.md](MATCH-CONTRACT.md), with Pydantic models in
`aw2_lab.match_contract`. Routes and controller behavior remain future work.
Cross-client requirements are:

- Pydantic models and FastAPI OpenAPI are the schema authority. Generate
  TypeScript types from the versioned schema; retain Python SDK types from shared
  Python models. Check generated artifacts against the schema in CI. Do not
  hand-maintain independent copies of gameplay models.
- Advertise protocol/schema versions and capabilities before joining a match.
  Reject incompatible major versions; tolerate additive optional fields. Keep
  unavailable observations explicit. Do not expose emulator pointers as public
  unit identities.
- Use zero-based coordinates, explicit paths, match identity, player-slot
  credentials, expected revision, and a unique request ID for mutations. Keep
  revisions within JavaScript's safe integer range or encode them as decimal
  strings; settle the representation in the public contract.
- Accepted commands return an ID. Poll their status with bounded backoff and a
  client deadline. Preserve request IDs and identical payloads across retries;
  never turn an uncertain outcome into a new gameplay request. A client timeout
  does not cancel or fail the server command. Resume polling after reconnection.
- Use structured error codes and details for authentication, ownership, stale
  revisions, unsupported features, rejection, rollback, and recovery-required.
  UI and SDK map the same codes; HTTP health does not imply battle readiness.
- Screenshots are authenticated HTTP image responses associated with frame and
  revision metadata. Display with nearest-neighbor scaling; revoke temporary
  object URLs. Reads and screenshots must not advance emulation.
- Serve the browser's production assets and API from one origin. A development
  server can proxy API requests. Native webviews have different origins: allow
  only configured application/development origins, including preflight requests,
  and explicitly test each platform. Do not enable wildcard credentialed CORS.
  CORS and Tauri CSP must permit only the configured server destinations.
- Keep credentials in memory by default. Do not put them in URLs, logs,
  screenshots, or general browser storage. Persistent browser login requires a
  future session design; optional native persistence requires an OS credential
  store and platform tests. Do not substitute a plaintext preferences file.
- Use HTTPS for remote/native mobile connections; development-only loopback
  exceptions must be explicit. Test platform transport policies before claiming
  mobile compatibility. Initial loopback service binding stays the default.

## Development, packaging, and updates

Pin tools through the existing flake lock. Add a separate client shell so the
normal Python/emulator environment does not require Rust or Node. Commit npm and
Cargo locks when those dependencies are introduced. Nix packages must fetch
dependencies through fixed-output derivations and build offline with declared
assets. No build may embed local server URLs, credentials, ROMs, or saves.

| Target | Development/build | Installation and updates | Evidence required |
| --- | --- | --- | --- |
| NixOS Linux x86_64 | Nix shell; Rust, pkg-config, GTK3/WebKitGTK 4.1, wrapping hooks; React/TypeScript/Vite when UI starts | Flake package with wrapped runtime closure; update by rebuilding against a reviewed lock | Packaged launch, API access, X11 and Wayland, display scaling and graphics |
| Linux aarch64 | Same pinned expressions, native builder or configured cross-build | Same Nix package | Native package build and runtime checks; expression availability alone is insufficient |
| Web | Nix Node environment; locked dependency build; serve assets with API | Deploy versioned assets; refresh to update; defer service worker/offline mutation queues | NixOS browser smoke check first, then Firefox/Chromium/WebKit and touch layouts |
| macOS | Native macOS runner with Rust, Xcode tools, WKWebView; Nix may supply auxiliary tools | Signed/notarized app and DMG; initially manual updates | Native build, launch, API, credentials, and supported architectures |
| Windows | Native Windows runner with Rust/MSVC, Windows SDK, WebView2 | Signed installer and manual updates | Native install, launch, API, credentials, and WebView2 provisioning |
| Android | Rust targets, JDK, Android SDK/NDK and emulator/device; assess pinned Nix tooling and licenses separately | Signed APK for testing; Play bundle/store process later | Device/emulator HTTP/TLS, lifecycle, touch UI and signed release build |
| iOS | macOS, Xcode, Rust iOS targets, Apple provisioning and device/simulator | Signed app via TestFlight/App Store when distribution is in scope | Native simulator/device build, transport policies, lifecycle and signing |

Nix does not replace Xcode, Apple provisioning, Windows SDK licensing, or store
accounts. The current flake exports Linux systems only; this ADR does not extend
server support to macOS/Windows. Automatic native updates need a separately
reviewed signing and rollback design. Match state belongs to the server and must
survive client updates or disconnections.

## Compatibility evidence and acceptance

No frontend stack is accepted solely from documentation. Record command, date,
host architecture, flake/Cargo locks, display backend, observed API response, and
errors for each prototype run. Keep generated artifacts outside Git. A health
response proves HTTP transport only; it does not prove gameplay or SDK support.

| Check | Current status | Required frequency |
| --- | --- | --- |
| NixOS packaged native prototype | Passed on x86_64; see evidence below | Every client/runtime dependency change |
| NixOS X11 and Wayland launch | Passed X11 and headless Weston Wayland; graphics/input caveats below | Every native runtime change; both before support acceptance |
| NixOS browser to local API | Passed headless Chromium health request | Every client transport/API change |
| Python SDK and two-client examples in Nix | Pending implementation | Every SDK/API change |
| Linux aarch64 runtime | Unverified | Before claiming support and on release candidates |
| macOS / Windows native | Unverified | Before claiming support and on release candidates |
| Android / iOS | Unverified | Before claiming support and on release candidates |

The first native prototype should embed a small page and read the existing
`GET /health` through the shared HTTP transport, using an explicitly configured
server address. It must handle an unavailable server visibly. Check the browser
version against the same endpoint, including origin policy. Test against the
real FastAPI application; label any ROM-independent launcher stub as such.

The NixOS package/runtime/browser gates have passed for this small prototype.
React is selected for the eventual gameplay UI; its build and runtime checks
will be added when the frontend is implemented.
Python SDK checks remain dependent on the SDK implementation and are tracked
under that implementation item. Other platforms remain planned until their own
evidence exists.

### Recorded NixOS prototype evidence

Verified on 2026-10-26 Pacific (2026-10-27 UTC), on x86_64 NixOS
26.11.20261024.674a202, Linux 6.18.56, with the working changes based on repository
commit `516957fe05b6a206c97ee8c20130696fc76d0339`.

- Nixpkgs: `09063bd1f2b36fd9fd793c36dfade7bd40a93dfc` from the existing flake lock.
  SHA-256 of `flake.lock`:
  `738543279658e4a340a21634402667d940a7622fa72839c5100837089235b6d6`.
- Cargo lock: Tauri 2.12.5, tauri-build 2.7.4; SHA-256:
  `99544c980a8459b40dc2550d3c82330a2fedec4ce17188726a355a8ce2a4b0be`.
- `nix develop .#client`: Cargo/Rust 1.99.0, Node 24.21.0, TypeScript 7.0.2,
  GTK 3.24.52 and WebKitGTK 2.54.1 resolved successfully.
- `nix build .#client-prototype --no-link --print-out-paths`: passed. Tested
  package output basename:
  `p6bx1nyxib72q0crlw8sp6whf0wkfn51-aw2-client-prototype-0.1.0`.
  The closure contains GTK3, WebKitGTK, librsvg, dconf and GSettings schemas.
  Cargo checks in the package build passed; there are no native unit tests yet.
- The prototype API helper used the existing `create_app`, the supported external
  ROM and the pinned headless mGBA. No launcher or HTTP response was stubbed.
  `/health` returned `{"status":"ok","emulator":"running"}`.
- Headless Chromium loaded `/client/` and its assets, executed browser `fetch`,
  and rendered that health response in the DOM. A separate `file:` asset check
  after stopping the API rendered `Connection failed: Failed to fetch`; it does
  not establish production `file:` origin support.
- Packaged native checks with `AW2_CLIENT_SMOKE_TEST=1`, a 20-second outer
  timeout, and `GDK_BACKEND=x11` / `wayland` each printed `Connected` and the
  health response, then exited zero. Wayland used Weston 16.0.0 with
  `--backend=headless --renderer=pixman --socket=aw2-client-check --idle-time=0`.
  API logs independently recorded the requests.
- X11 emitted GBM-buffer warnings. The headless Wayland check emitted Mesa and
  missing-keyboard-seat warnings. Neither prevented HTTP success. These checks
  establish webview startup and JavaScript/HTTP execution; rendered appearance,
  accelerated graphics, keyboard/touch interaction and fractional scaling remain
  unverified. Retest those in a real desktop before a gameplay UI release.
- The native-origin CORS response included
  `Access-Control-Allow-Origin: tauri://localhost`. An unrelated origin received
  no allow-origin header. The normal API was not changed to enable CORS.
- After the API stopped, the native smoke check printed
  `Connection failed: Load failed` and exited one. No sandbox-disabling flags or
  global library-path workarounds were used. Temporary API/emulator/compositor
  processes were stopped after the checks.

Reproduction commands and prototype limits are in
[the prototype README](../prototypes/client/README.md). The successful HTTP checks
do not verify gameplay, credentials, screenshots, the future SDK, native mobile
shells, or the complete browser compatibility matrix.

## Follow-up implementation order

1. Define the fixed match/public contract using these client constraints.
2. Implement the Milestone 3 controller, HTTP API, Python SDK, and examples.
   Verify the SDK under Nix as its deferred architecture integration check.
3. Introduce locked React/TypeScript/Vite dependencies, generated schema types and
   platform transport adapters when frontend implementation begins.
4. Check actual rendering, controls and scaling on NixOS desktops, including the
   observed graphics warnings, before claiming gameplay UI compatibility.
5. Add native platform builders, signing and credential adapters when those
   clients enter implementation scope; retain their unverified status until then.
