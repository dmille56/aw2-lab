{
  description = "Development environment for the AW2 emulator-backed platform";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.mgbaSource = {
    url = "github:mgba-emu/mgba/fd9dc5c2cbf234365068855851107e762fc6211b";
    flake = false;
  };

  outputs =
    {
      self,
      nixpkgs,
      mgbaSource,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      toolNames = [
        "python314"
        "lua"
        "pre-commit"
        "mypy"
        "nixfmt"
        "statix"
        "deadnix"
      ];
      environmentFor =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          pythonPackages = pkgs.python314Packages;
          mgba = import ./nix/mgba.nix { inherit pkgs mgbaSource; };
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
          tools = [
            application
            mgba
            pkgs.luaPackages.busted
            pkgs.luaPackages.luacheck
          ]
          ++ map (name: pkgs.${name}) toolNames;
          developmentPython = pkgs.python314.withPackages (
            pythonPackages: with pythonPackages; [
              fastapi
              httpx
              mcp
              mypy
              pydantic
              pytest
              python-lsp-server
              uvicorn
            ]
          );
          devTools = [
            developmentPython
            pkgs.ruff
          ];
        in
        {
          inherit
            application
            tools
            devTools
            mgba
            ;
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
      packages = forAllSystems (
        system:
        let
          env = environments.${system};
        in
        {
          aw2-lab = env.application;
          inherit (env) mgba;
          default = env.defaultPackage;
        }
      );

      devShells = forAllSystems (system: {
        default = environments.${system}.devShell;
      });
    };
}
