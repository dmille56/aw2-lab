{ pkgs, dependencies }:
let
  frontend = pkgs.runCommand "aw2-client-web-0.1.0" { nativeBuildInputs = [ pkgs.nodejs ]; } ''
    cp -r ${
      pkgs.lib.fileset.toSource {
        root = ../prototypes/client;
        fileset = pkgs.lib.fileset.unions [
          ../prototypes/client/web
          ../prototypes/client/package.json
          ../prototypes/client/vite.config.ts
          ../prototypes/client/tsconfig.json
          ../prototypes/client/tsconfig.build.json
        ];
      }
    } client
    chmod -R u+w client
    cd client
    mkdir node_modules
    ln -s ${dependencies}/node_modules/* node_modules/
    ln -s ${dependencies}/node_modules/.bin node_modules/.bin
    npm run build
    mv dist "$out"
  '';
in
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
    ];
  };
  passthru.web = frontend;
  preBuild = ''
    cp -r ${frontend} dist
  '';
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
