{ pkgs }:
pkgs.rustPlatform.buildRustPackage {
  pname = "aw2-client-prototype";
  version = "0.1.0";
  src = pkgs.lib.fileset.toSource {
    root = ../prototypes/client;
    fileset = pkgs.lib.fileset.unions [
      ../prototypes/client/Cargo.toml
      ../prototypes/client/Cargo.lock
      ../prototypes/client/build.rs
      ../prototypes/client/src
      ../prototypes/client/tauri.conf.json
      ../prototypes/client/icons
      ../prototypes/client/web
    ];
  };
  cargoLock.lockFile = ../prototypes/client/Cargo.lock;
  nativeBuildInputs = [
    pkgs.pkg-config
    pkgs.wrapGAppsHook3
    pkgs.rustfmt
    pkgs.clippy
  ];
  buildInputs = [
    pkgs.gtk3
    pkgs.webkitgtk_4_1
    pkgs.librsvg
  ];
  preFixup = ''
    # The primary Linux display produces a black WebKitGTK window with DMA-BUF.
    # Preserve an explicit user override on drivers where that renderer works.
    gappsWrapperArgs+=(--set-default WEBKIT_DISABLE_DMABUF_RENDERER 1)
  '';
  postBuild = ''
    cargo fmt --all -- --check
    cargo clippy --offline --locked --all-targets -- -D warnings
  '';
  meta = {
    description = "AW2 client runtime compatibility prototype";
    mainProgram = "aw2-client-prototype";
    platforms = pkgs.lib.platforms.linux;
  };
}
