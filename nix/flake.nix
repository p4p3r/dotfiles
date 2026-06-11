{
  description = "Hybrid Nix (nix-darwin + nix-homebrew + Home Manager) + chezmoi";

  inputs = {
    # Linux & general packages (25.11 stable). Used for everything inside
    # devenv projects and anything where reproducibility outweighs freshness.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

    # macOS-specific nixpkgs branch that matches nix-darwin 25.11
    nixpkgs-darwin.url = "github:NixOS/nixpkgs/nixpkgs-25.11-darwin";

    # Rolling unstable nixpkgs. Used for "I want this CLI on $PATH and want
    # it close to upstream HEAD" tools — see pkgs-unstable usage in common.nix.
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";

    # nix-darwin must follow the darwin branch of nixpkgs
    darwin.url = "github:nix-darwin/nix-darwin/nix-darwin-25.11";
    darwin.inputs.nixpkgs.follows = "nixpkgs-darwin";

    # Home Manager release matching 25.11, follow the Linux/general nixpkgs
    home-manager.url = "github:nix-community/home-manager/release-25.11";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    # nix-homebrew (no special follows needed)
    nix-homebrew.url = "github:zhaofengli/nix-homebrew";

    # Private Nix configuration (work projects and sensitive configs)
    nix-private = {
      url = "git+ssh://git@github.com/p4p3r/dotfiles-private.git";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ self, nixpkgs, nixpkgs-unstable, home-manager, darwin, nix-homebrew, ... }:
  let
    username = let u = builtins.getEnv "USER"; in if u == "" then "paper" else u;
    primaryUser = let p = builtins.getEnv "PRIMARY_USER"; in if p == "" then "paper" else p;
    hostName = let h = builtins.getEnv "HOST_NAME"; in if h == "" then "paperware" else h;

    # Helper: build a pkgs-unstable for a given system, passed into both
    # darwin + home-manager configs via specialArgs / extraSpecialArgs so
    # modules can do `pkgs-unstable.foo` for bleeding-edge tools.
    mkUnstable = system: import nixpkgs-unstable {
      inherit system;
      config.allowUnfree = true;
    };

    mkDarwin = { user ? username, primary ? primaryUser, profiles ? [ "p4p3r" ] }: darwin.lib.darwinSystem {
      system = "aarch64-darwin";
      specialArgs = {
        inherit inputs user primary hostName;
        pkgs-unstable = mkUnstable "aarch64-darwin";
      };
      modules = [
        { nixpkgs.config.allowUnfree = true; }
        ./modules/nix-settings.nix
        ./modules/darwin-homebrew.nix
        inputs.nix-private.darwinModule
        { private.profiles = profiles; }
        # Force the correct user, overriding any empty value from the imported module:
        ({ lib, ... }: {
          nix-homebrew.user = lib.mkForce user;
        })
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
          # Disable Cmd+H (Hide) in Ghostty so it passes through to Zellij
          system.defaults.CustomUserPreferences."com.mitchellh.ghostty" = {
            NSUserKeyEquivalents = { "Hide Ghostty" = "@~^$h"; };
          };
          users.users.root.home = lib.mkForce "/var/root";
          users.users.${user} = {
            home = "/Users/${user}";
            shell = pkgs.fish;
          };
          programs.fish.enable = true;
          environment.shells = [ pkgs.fish ];
          environment.variables.SHELL = "/run/current-system/sw/bin/fish";
          launchd.user.envVariables.SHELL = "/run/current-system/sw/bin/fish";

          # Activation script to install global npm packages and user CLIs.
          # Self-updating upstream tools (claude, opencode) are bootstrapped via
          # their official installers rather than nix-packaged, so the tools'
          # own updaters can manage versions without fighting nix pinning.
          # Node comes from nixpkgs (same nodejs_22 the home devenv uses); npm
          # globals land in /Users/${user}/.npm-global so they're user-owned and
          # don't try to write to the read-only nix store. That prefix's bin dir
          # is added to the user's PATH via home.sessionPath in common.nix.
          system.activationScripts.postActivation.text = ''
            # Global npm installs — user-scoped to ~/.npm-global/{lib,bin}
            # - @openai/codex: OpenAI Codex CLI
            # - @zed-industries/*-acp: ACP bridges so Zed can talk to Codex / Claude Code
            echo "Installing global npm packages..."
            sudo -u ${user} -H bash -c '
              export PATH=${pkgs.nodejs_22}/bin:$PATH
              export NPM_CONFIG_PREFIX=$HOME/.npm-global
              mkdir -p "$NPM_CONFIG_PREFIX"
              npm install -g @openai/codex || true
              npm install -g @zed-industries/codex-acp || true
              npm install -g @agentclientprotocol/claude-agent-acp || true
            '

            # User-scoped CLIs via upstream installers. postActivation runs as root,
            # so drop to the user with `sudo -u` to write into /Users/${user}/.local.
            if [ ! -x /Users/${user}/.local/bin/claude ]; then
              echo "Installing Claude Code (native installer)..."
              sudo -u ${user} -H bash -c 'curl -fsSL https://claude.ai/install.sh | bash' || true
            fi
            # opencode's installer writes to ~/.opencode/bin/opencode, not ~/.local/bin.
            if [ ! -x /Users/${user}/.opencode/bin/opencode ]; then
              echo "Installing opencode..."
              sudo -u ${user} -H bash -c 'curl -fsSL https://opencode.ai/install | bash' || true
            fi

            # pup (Datadog) — installed from GitHub releases. README lists
            # brew, cargo, or manual download; no upstream install script.
            # Fetch latest tarball, extract into ~/.local/bin/pup.
            if [ ! -x /Users/${user}/.local/bin/pup ]; then
              echo "Installing pup (DataDog/pup latest release)..."
              sudo -u ${user} -H bash -c '
                export PATH=${pkgs.curl}/bin:${pkgs.gnutar}/bin:${pkgs.gzip}/bin:${pkgs.gnused}/bin:$PATH
                mkdir -p "$HOME/.local/bin"
                pup_ver="$(curl -fsSL https://api.github.com/repos/DataDog/pup/releases/latest \
                  | sed -n "s/.*\"tag_name\": *\"v\([^\"]*\)\".*/\1/p" | head -1)"
                if [ -n "$pup_ver" ]; then
                  arch="$(uname -m)"
                  case "$arch" in
                    arm64|aarch64) pup_arch="arm64" ;;
                    x86_64)        pup_arch="x86_64" ;;
                    *)             pup_arch="$arch" ;;
                  esac
                  url="https://github.com/DataDog/pup/releases/download/v$pup_ver/pup_''${pup_ver}_Darwin_''${pup_arch}.tar.gz"
                  curl -fsSL "$url" | tar -xzC "$HOME/.local/bin" pup \
                    || echo "WARN: pup install failed (non-fatal)"
                else
                  echo "WARN: could not resolve pup latest version"
                fi
              ' || true
            fi
          '';

          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.backupFileExtension = "hm-backup";
          home-manager.extraSpecialArgs = {
            pkgs-unstable = mkUnstable "aarch64-darwin";
          };
          home-manager.users.${user} = { pkgs, ... }: {
            imports = [
              ./modules/common.nix
              ./modules/git-ssh.nix
              inputs.nix-private.homeManagerModule
            ];
            private.profiles = profiles;
            home.username = "${user}";
            home.homeDirectory = "/Users/${user}";
          };
        })
      ];
    };

    mkHome = { system, user ? username, profiles ? [ "p4p3r" ] }:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        extraSpecialArgs = {
          pkgs-unstable = mkUnstable system;
        };
        modules = [
          { nixpkgs.config.allowUnfree = true; }
          ./modules/common.nix
          ./modules/git-ssh.nix
          inputs.nix-private.homeManagerModule
          {
            home.username = user;
            home.homeDirectory = "/home/${user}";
            private.profiles = profiles;
          }
        ];
      };

    # Linux profile list: from PROFILES env var when set
    # (e.g. `PROFILES=work home-manager switch --flake .#paper@linux --impure`).
    # Falls back to ["p4p3r"] for parity with mkHome's default.
    linuxProfiles = let
      env = builtins.getEnv "PROFILES";
    in
      if env == "" then [ "p4p3r" ]
      else nixpkgs.lib.splitString "," env;

    linuxSystems = [ "x86_64-linux" "aarch64-linux" ];
  in {
    darwinConfigurations."${hostName}" = mkDarwin {
      user = username;
      # Personal profile plus any extra profiles contributed by the private
      # input (kept out of this public flake). `or [ ]` keeps eval working
      # before the private input's lock is updated to expose extraProfiles.
      profiles = [ "p4p3r" ] ++ (inputs.nix-private.extraProfiles or [ ]);
    };

    # Linux home-manager configs for both x86_64 and aarch64.
    # Default `@linux` alias targets x86_64-linux to preserve the existing
    # `nix_switch` invocation contract. Use `@linux-aarch64` (or pick via the
    # arch-aware nix_switch.fish branch) on Graviton/Apple-silicon Linux boxes.
    homeConfigurations = {
      "${username}@linux"          = mkHome { system = "x86_64-linux";  user = username; profiles = linuxProfiles; };
      "${username}@linux-x86_64"   = mkHome { system = "x86_64-linux";  user = username; profiles = linuxProfiles; };
      "${username}@linux-aarch64"  = mkHome { system = "aarch64-linux"; user = username; profiles = linuxProfiles; };
    };

    # Dev shells with toolchains — one per supported system.
    devShells = nixpkgs.lib.genAttrs ([ "aarch64-darwin" ] ++ linuxSystems) (system: {
      default = let
        pkgs = nixpkgs.legacyPackages.${system};
      in pkgs.mkShell {
        packages = import ./lib/devtoolchain.nix { inherit pkgs; };
      };
    });

    checks = {
      # Build the macOS system derivation (does NOT switch)
      aarch64-darwin.darwin-build = self.darwinConfigurations."${hostName}".system;

      # Build the Linux Home Manager activation packages (does NOT switch)
      x86_64-linux.hm-build  = self.homeConfigurations."${username}@linux-x86_64".activationPackage;
      aarch64-linux.hm-build = self.homeConfigurations."${username}@linux-aarch64".activationPackage;
    };

    formatter = nixpkgs.lib.genAttrs ([ "aarch64-darwin" ] ++ linuxSystems)
      (system: nixpkgs.legacyPackages.${system}.nixpkgs-fmt);
  };
}
