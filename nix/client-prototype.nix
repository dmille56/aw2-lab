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
  meta = {
    description = "AW2 client runtime compatibility prototype";
    mainProgram = "aw2-client-prototype";
    platforms = pkgs.lib.platforms.linux;
  };
}
