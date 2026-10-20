{
  description = "Development environment for the AW2 emulator-backed platform";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      toolNames = [ "python3" "lua" "mgba" ];
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = map (name: pkgs.${name}) toolNames;
        in
        {
          default = pkgs.symlinkJoin {
            name = "aw2-lab-tools";
            paths = tools;
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = map (name: pkgs.${name}) toolNames;
        in
        {
          default = pkgs.mkShell {
            packages = tools;
          };
        });
    };
}
