{
  description = "Hybrid Nix (nix-darwin + nix-homebrew + Home Manager) + chezmoi + private overlay";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    home-manager.url = "github:nix-community/home-manager/release-24.05";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    darwin.url = "github:LnL7/nix-darwin";
    darwin.inputs.nixpkgs.follows = "nixpkgs";
    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
    nix-homebrew.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = inputs@{ self, nixpkgs, home-manager, darwin, nix-homebrew, ... }:
  let
    username = builtins.getEnv "USER";
    hostName = let h = builtins.getEnv "HOST_NAME"; in if h == "" then "paperware" else h;

    mkDarwin = { user ? username, }: darwin.lib.darwinSystem {
      system = "aarch64-darwin";
      modules = [
        ./nix/modules/darwin-homebrew.nix
        ./nix/modules/common.nix
        ./nix/modules/private-restore.nix
        home-manager.darwinModules.home-manager
        {
          networking.hostName = hostName;
          security.pam.services.sudo_local.touchIdAuth = true;
          system.defaults.NSGlobalDomain = {
            KeyRepeat = 2;
            InitialKeyRepeat = 15;
          };
          users.users.${user}.home = "/Users/${user}";
          programs.fish.enable = true;
          environment.shells = [ pkgs.fish ];
          users.users.${user}.shell = pkgs.fish;
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.users.${user} = { pkgs, ... }: {
            imports = [ ./nix/modules/common.nix ];
            home.username = "${user}";
            home.homeDirectory = "/Users/${user}";
          };
        }
      ];
    };

    mkHome = { system, user ? username, }:
      let pkgs = import nixpkgs { inherit system; };
      in home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        modules = [
          ./nix/modules/common.nix
          ./nix/modules/private-restore.nix
          { home.username = "${user}"; home.homeDirectory = "/home/${user}"; }
        ];
      };
  in {
    darwinConfigurations.mac = mkDarwin { user = username; };
    homeConfigurations."${username}@linux" = mkHome { system = "x86_64-linux"; user = username; };

    # Dev shells with toolchains
    devShells = let
      pkgsDarwin = import nixpkgs { system = "aarch64-darwin"; };
      pkgsLinux  = import nixpkgs { system = "x86_64-linux"; };
      mkShell = pkgs: pkgs.mkShell {
        packages = import ./nix/lib/devtoolchain.nix { inherit pkgs; };
      };
    in {
      aarch64-darwin.default = mkShell pkgsDarwin;
      x86_64-linux.default   = mkShell pkgsLinux;
    };

    checks = {
      # Build the macOS system derivation (does NOT switch)
      aarch64-darwin.darwin-build = self.darwinConfigurations.mac.system;

      # Build the Linux Home Manager activation package (does NOT switch)
      x86_64-linux.hm-build = self.homeConfigurations."${username}@linux".activationPackage;
    };

    formatter.aarch64-darwin = nixpkgs.legacyPackages.aarch64-darwin.nixpkgs-fmt;
    formatter.x86_64-linux   = nixpkgs.legacyPackages.x86_64-linux.nixpkgs-fmt;
  };
}
