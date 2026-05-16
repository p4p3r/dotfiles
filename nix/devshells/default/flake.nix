{
  # Default home devshell. Activated in $HOME via direnv when no project-specific
  # devenv is in scope.
  #
  # Convention mirrors the top-level flake (nix/flake.nix):
  #   - `pkgs.X`          → 25.11 stable. Use for toolchains where reproducibility
  #                         matters more than version freshness.
  #   - `pkgs-unstable.X` → rolling nixos-unstable. Use for tools you want close
  #                         to upstream HEAD.
  inputs = {
    nixpkgs.url           = "github:NixOS/nixpkgs/nixos-25.11";
    nixpkgs-unstable.url  = "github:NixOS/nixpkgs/nixos-unstable";
    devenv.url            = "github:cachix/devenv";
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, devenv, ... } @ inputs:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forEachSystem = f: nixpkgs.lib.genAttrs systems (system: f system);
    in
    {
      devShells = forEachSystem (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pkgs-unstable = import nixpkgs-unstable {
            inherit system;
            config.allowUnfree = true;
          };
        in
        {
          default = devenv.lib.mkShell {
            inherit inputs pkgs;
            modules = [
              ({ ... }: { _module.args.pkgs-unstable = pkgs-unstable; })
              ./devenv.nix
            ];
          };
        });
    };
}
