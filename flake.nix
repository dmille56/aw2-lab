{
  description = "Development environment for the AW2 emulator-backed platform";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      toolNames = [ "python3" "lua" "mgba" "pre-commit" ];
      environmentFor = system:
        let
          pkgs = import nixpkgs { inherit system; };
          pythonPackages = pkgs.python3Packages;
          application = pythonPackages.buildPythonApplication {
            pname = "aw2-lab";
            version = "0.1.0";
            src = self;
            pyproject = true;
            build-system = [ pythonPackages.hatchling ];
            dependencies = with pythonPackages; [
              fastapi
              httpx
              mcp
              pydantic
              uvicorn
            ];
            nativeCheckInputs = [ pythonPackages.pytestCheckHook ];
            pythonImportsCheck = [ "aw2_lab" ];
            meta.mainProgram = "aw2-lab";
          };
          tools = [ application ] ++ map (name: pkgs.${name}) toolNames;
          developmentPython = pkgs.python3.withPackages (pythonPackages: with pythonPackages; [
            fastapi
            httpx
            mcp
            pydantic
            pytest
            uvicorn
          ]);
          devTools = [ developmentPython pkgs.ruff ];
        in
        {
          inherit application tools devTools;
          defaultPackage = pkgs.symlinkJoin {
            name = "aw2-lab-tools";
            paths = tools;
            meta.mainProgram = "aw2-lab";
          };
          devShell = pkgs.mkShell {
            packages = tools ++ devTools;
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        };
      environments = forAllSystems environmentFor;
    in
    {
      packages = forAllSystems (system:
        let env = environments.${system};
        in {
          aw2-lab = env.application;
          default = env.defaultPackage;
        });

      devShells = forAllSystems (system: {
        default = environments.${system}.devShell;
      });
    };
}
