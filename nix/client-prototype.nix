{ pkgs }:
pkgs.rustPlatform.buildRustPackage {
  pname = "aw2-client-prototype";
  version = "0.1.0";
  src = ../prototypes/client;
  cargoLock.lockFile = ../prototypes/client/Cargo.lock;
  nativeBuildInputs = [
    pkgs.pkg-config
    pkgs.wrapGAppsHook3
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
  meta = {
    description = "AW2 client runtime compatibility prototype";
    mainProgram = "aw2-client-prototype";
    platforms = pkgs.lib.platforms.linux;
  };
}
