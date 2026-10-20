{ pkgs, mgbaSource }:

pkgs.mgba.overrideAttrs (previous: {
  version = "0.11-dev-${mgbaSource.shortRev}";
  src = mgbaSource;
  patches = (previous.patches or []) ++ [
    ./patches/mgba-quiet-script-startup.patch
  ];
  buildInputs = previous.buildInputs ++ [ pkgs.json_c pkgs.freetype ];
  cmakeFlags = previous.cmakeFlags ++ [
    "-DBUILD_HEADLESS=ON"
    "-DBUILD_QT=ON"
    "-DBUILD_SDL=OFF"
    "-DENABLE_SCRIPTING=ON"
    "-DUSE_LUA=5.2"
  ];
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    # The headless frontend requires a positional argument even for help.
    "$out/bin/mgba-headless" --help unused.gba > headless-help.txt
    "$out/bin/mgba-qt" --help > windowed-help.txt
    grep -F -- '--script' headless-help.txt
    grep -F -- '--script' windowed-help.txt
    runHook postInstallCheck
  '';
  meta = previous.meta // { mainProgram = "mgba-headless"; };
})
