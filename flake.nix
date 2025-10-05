{
  description = "Hybrid Nix (nix-darwin + nix-homebrew + Home Manager) + chezmoi + private overlay";

  inputs = {
    # Linux & general packages (25.11 stable)
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

    # macOS-specific nixpkgs branch that matches nix-darwin 25.11
    nixpkgs-darwin.url = "github:NixOS/nixpkgs/nixpkgs-25.05-darwin";

    # nix-darwin must follow the darwin branch of nixpkgs
    darwin.url = "github:nix-darwin/nix-darwin/nix-darwin-25.05";
    darwin.inputs.nixpkgs.follows = "nixpkgs-darwin";

    # Home Manager release matching 25.11, follow the Linux/general nixpkgs
    home-manager.url = "github:nix-community/home-manager/release-25.05";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    # nix-homebrew (no special follows needed)
    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
  };

  outputs = inputs@{ self, nixpkgs, home-manager, darwin, nix-homebrew, ... }:
  let
    username = let u = builtins.getEnv "USER"; in if u == "" then "paper" else u;
    primaryUser = let p = builtins.getEnv "PRIMARY_USER"; in if p == "" then "paper" else p;
    hostName = let h = builtins.getEnv "HOST_NAME"; in if h == "" then "paperware" else h;

    mkDarwin = { user ? username, primary ? primaryUser }: darwin.lib.darwinSystem {
      system = "aarch64-darwin";
      specialArgs = { inherit inputs; };
      modules = [
        { nixpkgs.config.allowUnfree = true; }
        ./nix/modules/darwin-homebrew.nix
        home-manager.darwinModules.home-manager
        ({ config, pkgs, lib, ... }: {
          system.stateVersion = 6;
          system.primaryUser = primary;
          networking.hostName = hostName;

          # Enable Nix experimental features
          nix.settings.experimental-features = [ "nix-command" "flakes" ];

          security.pam.services.sudo_local.touchIdAuth = true;
          system.defaults.NSGlobalDomain = {
            KeyRepeat = 2;
            InitialKeyRepeat = 15;
          };
          users.users.root.home = lib.mkForce "/var/root";
          users.users.${user} = {
            home = "/Users/${user}";
            shell = pkgs.fish;
          };
          programs.fish.enable = true;
          environment.shells = [ pkgs.fish ];
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.users.${user} = { pkgs, ... }: {
            imports = [ ./nix/modules/common.nix ./nix/modules/private-restore.nix ];
            home.username = "${user}";
            home.homeDirectory = "/Users/${user}";
          };
        })
      ];
    };

    mkHome = { system, user ? username }:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        modules = [
          { nixpkgs.config.allowUnfree = true; }
          ./nix/modules/common.nix
          ./nix/modules/private-restore.nix
          { home.username = user; home.homeDirectory = "/home/${user}"; }
        ];
      };

  in {
    darwinConfigurations.mac = mkDarwin { user = username; };
    homeConfigurations."${username}@linux" = mkHome { system = "x86_64-linux"; user = username; };

    # Dev shells with toolchains
    devShells = {
      aarch64-darwin.default = let
        pkgs = nixpkgs.legacyPackages.aarch64-darwin;
      in pkgs.mkShell {
        packages = import ./nix/lib/devtoolchain.nix { inherit pkgs; };
      };
    
      x86_64-linux.default = let
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
      in pkgs.mkShell {
        packages = import ./nix/lib/devtoolchain.nix { inherit pkgs; };
      };
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
