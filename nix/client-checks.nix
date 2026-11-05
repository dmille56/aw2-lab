{ pkgs, python }:
let
  manifest = builtins.fromJSON (builtins.readFile ../prototypes/client/package.json);
  dependencies = pkgs.buildNpmPackage {
    pname = "aw2-client-check-dependencies";
    version = "0.1.0";
    src = pkgs.lib.fileset.toSource {
      root = ../prototypes/client;
      fileset = pkgs.lib.fileset.unions [
        ../prototypes/client/package.json
        ../prototypes/client/package-lock.json
      ];
    };
    npmDepsHash = "sha256-hut3DV+TlHDTQkRkykNPj2ikxNUcOlbV1ts7NfrRh6g=";
    npmFlags = [ "--ignore-scripts" ];
    dontNpmBuild = true;
    nativeBuildInputs = [ pkgs.autoPatchelfHook ];
    buildInputs = [ pkgs.stdenv.cc.cc.lib ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp -r node_modules package-lock.json "$out/"
      runHook postInstall
    '';
  };
  tool = pkgs.writeShellApplication {
    name = "aw2-client-check";
    runtimeInputs = [
      python
      pkgs.nodejs
      pkgs.cargo
      pkgs.rustfmt
      pkgs.ruff
      pkgs.nix
      pkgs.xvfb-run
    ];
    text = ''
      export AW2_CLIENT_NODE_MODULES="${dependencies}/node_modules"
      export AW2_CLIENT_LOCK="${dependencies}/package-lock.json"
      export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
      export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
      export FONTCONFIG_FILE="${pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; }}"
      exec python ${../prototypes/client/check.py} --repo "$PWD" "$@"
    '';
  };
in
assert pkgs.lib.assertMsg (
  manifest.devDependencies."@playwright/test" == pkgs.playwright-driver.version
) "The client Playwright version must match the browsers pinned by nixpkgs";
{
  inherit tool dependencies;
}
