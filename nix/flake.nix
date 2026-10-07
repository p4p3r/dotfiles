{
  description = "Hybrid Nix (nix-darwin + nix-homebrew + Home Manager) + chezmoi";

  inputs = {
    # Linux & general packages (26.05 stable). Used for everything inside
    # devenv projects and anything where reproducibility outweighs freshness.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    # macOS-specific nixpkgs branch that matches nix-darwin 26.05
    nixpkgs-darwin.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";

    # Rolling unstable nixpkgs. Used for "I want this CLI on $PATH and want
    # it close to upstream HEAD" tools — see pkgs-unstable usage in common.nix.
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";

    # nix-darwin must follow the darwin branch of nixpkgs
    darwin.url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
    darwin.inputs.nixpkgs.follows = "nixpkgs-darwin";

    # Home Manager release matching 26.05, follow the Linux/general nixpkgs
    home-manager.url = "github:nix-community/home-manager/release-26.05";
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
            # - @agentclientprotocol/*-acp: ACP bridges so Zed can talk to Codex / Claude Code
            echo "Installing global npm packages..."
            sudo -u ${user} -H bash -c '
              export PATH=${pkgs.nodejs_22}/bin:${pkgs.bash}/bin:${pkgs.coreutils}/bin:${pkgs.jq}/bin:$PATH
              export NPM_CONFIG_PREFIX=$HOME/.npm-global
              mkdir -p "$NPM_CONFIG_PREFIX"
              ${pkgs.bash}/bin/bash ${./scripts/codex-npm-install.sh} ensure "$NPM_CONFIG_PREFIX" \
                || echo "WARN: no healthy Codex install could be proven"
              npm uninstall -g @zed-industries/codex-acp 2>/dev/null || true      # renamed -> @agentclientprotocol
              npm install -g @agentclientprotocol/codex-acp || true
              npm uninstall -g @zed-industries/claude-code-acp 2>/dev/null || true # renamed -> @agentclientprotocol
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

            # agent-deck — latest GitHub release. The Homebrew tap
            # (asheshgoplani/tap) lags upstream releases, so the version is
            # managed here instead of via brew. ~/.local/bin precedes
            # /opt/homebrew/bin on PATH, so this binary wins over any brew copy.
            # Resolves the latest release each rebuild and re-fetches only when
            # the installed version differs; checksum-verified before install.
            echo "Checking agent-deck (latest GitHub release)..."
            sudo -u ${user} -H bash -c '
              export PATH=${pkgs.curl}/bin:${pkgs.gnutar}/bin:${pkgs.gzip}/bin:${pkgs.gnused}/bin:${pkgs.gnugrep}/bin:${pkgs.coreutils}/bin:$PATH
              mkdir -p "$HOME/.local/bin"
              latest="$(curl -fsSL https://api.github.com/repos/asheshgoplani/agent-deck/releases/latest \
                | sed -n "s/.*\"tag_name\": *\"v\{0,1\}\([^\"]*\)\".*/\1/p" | head -1)"
              if [ -z "$latest" ]; then
                echo "WARN: could not resolve agent-deck latest version (non-fatal)"
                exit 0
              fi
              installed="$("$HOME/.local/bin/agent-deck" --version 2>/dev/null | grep -oE "[0-9]+\.[0-9]+\.[0-9]+" | head -1)"
              if [ "$installed" = "$latest" ]; then
                exit 0
              fi
              echo "Installing agent-deck v$latest (was: ''${installed:-none})..."
              case "$(uname -m)" in
                arm64|aarch64) ad_arch="arm64" ;;
                x86_64)        ad_arch="amd64" ;;
                *)             ad_arch="$(uname -m)" ;;
              esac
              base="https://github.com/asheshgoplani/agent-deck/releases/download/v$latest"
              tarball="agent-deck_''${latest}_darwin_''${ad_arch}.tar.gz"
              tmp="$(mktemp -d)"
              if curl -fsSL "$base/$tarball" -o "$tmp/ad.tar.gz" \
                 && curl -fsSL "$base/checksums.txt" -o "$tmp/checksums.txt"; then
                want="$(grep "$tarball" "$tmp/checksums.txt" | cut -d" " -f1)"
                got="$(sha256sum "$tmp/ad.tar.gz" | cut -d" " -f1)"
                if [ -n "$want" ] && [ "$want" = "$got" ]; then
                  tar -xzC "$HOME/.local/bin" -f "$tmp/ad.tar.gz" agent-deck
                  echo "agent-deck v$latest installed."
                else
                  echo "WARN: agent-deck checksum mismatch (want=$want got=$got); skipped"
                fi
              else
                echo "WARN: agent-deck download failed (non-fatal)"
              fi
              rm -rf "$tmp"
            ' || true
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
              ./modules/homebrew-trust.nix
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

    maintenanceRuntimeConfiguration = system:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        modules = [
          ./modules/agent-deck-maintenance.nix
          {
            home.username = "maintenance-check";
            home.homeDirectory = "/home/maintenance-check";
            home.stateVersion = "24.05";
            programs.agent-deck-maintenance = {
              enable = true;
              hostAlias = "maintenance-check";
              workDirectory = "/home/maintenance-check";
              repositoryRoots = [ "/project/100%nice" ];
            };
          }
        ];
      };

    maintenanceRuntimeCheck = system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        generation = (maintenanceRuntimeConfiguration system).activationPackage;
      in
      pkgs.runCommand "agent-deck-maintenance-runtime-check" { } ''
        service="${generation}/home-files/.config/systemd/user/agent-deck-maintenance.service"
        timer="${generation}/home-files/.config/systemd/user/agent-deck-maintenance.timer"
        test -f "$service"
        test -f "$timer"
        ${pkgs.gnugrep}/bin/grep -F -- "--repo /project/100%%nice" "$service"
        ${pkgs.gnugrep}/bin/grep -F -- \
          "--codex-executable /home/maintenance-check/.npm-global/bin/codex" "$service"
        test "$(${pkgs.gnugrep}/bin/grep -F -c -- \
          "ConditionFileIsExecutable=" "$service")" -eq 2
        # npm-installed agent launchers need Node even without an interactive shell.
        service_path="$(${pkgs.gnused}/bin/sed -n 's/^Environment=PATH=//p' "$service")"
        test -n "$service_path"
        PATH="$service_path" ${pkgs.coreutils}/bin/env node --eval 'if (!process.versions.node) process.exit(1)'
        PATH="$service_path" ${pkgs.coreutils}/bin/env tmux -V
        PATH="$service_path" ${pkgs.coreutils}/bin/env bash --version >/dev/null
        PATH="$service_path" ${pkgs.coreutils}/bin/env ps --version
        PATH="$service_path" ${pkgs.coreutils}/bin/env pgrep --version
        for companion in agent-deck-maintenance-controller agent-deck-maintenance-collector; do
          PATH="$service_path" "${generation}/home-path/bin/$companion" --help >/dev/null
        done
        for directive in PrivateDevices ProtectClock ProtectKernelLogs ProtectKernelModules; do
          if ${pkgs.gnugrep}/bin/grep -q "^$directive=" "$service"; then
            echo "user service must not alter the capability bounding set via $directive" >&2
            exit 1
          fi
        done
        for setting in \
          NoNewPrivileges=true \
          ProtectControlGroups=true \
          ProtectKernelTunables=true \
          ProtectSystem=strict \
          RestrictRealtime=true \
          RestrictSUIDSGID=true \
          LockPersonality=true \
          SystemCallArchitectures=native; do
          ${pkgs.gnugrep}/bin/grep -F -x -- "$setting" "$service"
        done
        runtime_directory="$TMPDIR/systemd-runtime"
        mkdir -p "$runtime_directory"
        XDG_RUNTIME_DIR="$runtime_directory" \
          ${pkgs.systemd}/bin/systemd-analyze verify \
            --user --recursive-errors=no "$service" "$timer"
        touch "$out"
      '';

    slackWatchdogRuntimeConfiguration = system:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        modules = [
          ./modules/agent-deck-slack-watchdog.nix
          {
            home.username = "watchdog-check";
            home.homeDirectory = "/home/watchdog-check";
            home.stateVersion = "24.05";
            programs.agent-deck-slack-watchdog = {
              enable = true;
              settingsFile = "/home/watchdog-check/.config/agent-deck/slack-watchdog.json";
            };
          }
        ];
      };

    slackWatchdogRuntimeCheck = system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        generation = (slackWatchdogRuntimeConfiguration system).activationPackage;
      in
      pkgs.runCommand "agent-deck-slack-watchdog-runtime-check" { } ''
        service="${generation}/home-files/.config/systemd/user/agent-deck-slack-watchdog.service"
        timer="${generation}/home-files/.config/systemd/user/agent-deck-slack-watchdog.timer"
        test -f "$service"
        test -f "$timer"
        ${pkgs.gnugrep}/bin/grep -F -x -- \
          "ConditionPathExists=/home/watchdog-check/.config/agent-deck/slack-watchdog.json" "$service"
        ${pkgs.gnugrep}/bin/grep -F -- "--state %S/agent-deck-slack-watchdog/state.json" "$service"
        ${pkgs.gnugrep}/bin/grep -F -- "--systemctl ${pkgs.systemd}/bin/systemctl" "$service"
        ${pkgs.gnugrep}/bin/grep -F -x -- "RestrictAddressFamilies=AF_UNIX" "$service"
        ${pkgs.gnugrep}/bin/grep -F -x -- "OnUnitInactiveSec=1m" "$timer"
        ! ${pkgs.gnugrep}/bin/grep -q '^Restart=' "$service"
        ! ${pkgs.gnugrep}/bin/grep -q '^EnvironmentFile=' "$service"
        for directive in PrivateDevices ProtectClock ProtectKernelLogs ProtectKernelModules; do
          if ${pkgs.gnugrep}/bin/grep -q "^$directive=" "$service"; then
            echo "user service must not alter the capability bounding set via $directive" >&2
            exit 1
          fi
        done
        for setting in \
          NoNewPrivileges=true \
          ProtectControlGroups=true \
          ProtectKernelTunables=true \
          ProtectSystem=strict \
          RestrictRealtime=true \
          RestrictSUIDSGID=true \
          LockPersonality=true \
          SystemCallArchitectures=native; do
          ${pkgs.gnugrep}/bin/grep -F -x -- "$setting" "$service"
        done
        "${generation}/home-path/bin/agent-deck-slack-watchdog" --help >/dev/null
        runtime_directory="$TMPDIR/systemd-runtime"
        mkdir -p "$runtime_directory"
        XDG_RUNTIME_DIR="$runtime_directory" \
          ${pkgs.systemd}/bin/systemd-analyze verify \
            --user --recursive-errors=no "$service" "$timer"
        touch "$out"
      '';

    signedIngressConfiguration = system: enabled:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        modules = [
          ./modules/agent-deck-signed-ingress.nix
          {
            home.username = "ingress-check";
            home.homeDirectory = "/home/ingress-check";
            home.stateVersion = "24.05";
            programs.agent-deck-signed-ingress = {
              enable = enabled;
              runtimeConfig = "/run/ingress-check/config.json";
            };
          }
        ];
      };

    signedIngressCheck = system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        enabled = signedIngressConfiguration system true;
        disabled = signedIngressConfiguration system false;
        generation = enabled.activationPackage;
      in
      assert !(disabled.config.programs.agent-deck-signed-ingress.enable);
      assert !(disabled.config.systemd.user.services ? agent-deck-signed-ingress);
      pkgs.runCommand "agent-deck-signed-ingress-offline-check" { } ''
        export HOME="$TMPDIR/home"
        export XDG_CONFIG_HOME="$HOME/config" XDG_STATE_HOME="$HOME/state" XDG_RUNTIME_DIR="$HOME/run"
        export PYTHONDONTWRITEBYTECODE=1
        mkdir -p "$XDG_RUNTIME_DIR" private_dot_local/bin tests
        chmod 0700 "$HOME" "$XDG_RUNTIME_DIR"
        cp ${../private_dot_local/bin/executable_agent-deck-signed-ingress} \
          private_dot_local/bin/executable_agent-deck-signed-ingress
        cp ${../tests/test_agent_deck_signed_ingress.py} tests/test_agent_deck_signed_ingress.py
        ${pkgs.python3}/bin/python3 -m unittest discover -s tests -p test_agent_deck_signed_ingress.py -v
        "${enabled.config.programs.agent-deck-signed-ingress.package}/bin/agent-deck-signed-ingress" --help >/dev/null
        service="${generation}/home-files/.config/systemd/user/agent-deck-signed-ingress.service"
        test -f "$service"
        for setting in UMask=0077 StateDirectoryMode=0700 RuntimeDirectoryMode=0700 \
          Restart=on-failure RestartSec=5 StartLimitIntervalSec=300 StartLimitBurst=3 \
          TimeoutStartSec=10 TimeoutStopSec=10 LimitCORE=0 NoNewPrivileges=true ProtectSystem=strict \
          RestrictAddressFamilies=AF_UNIX RestrictAddressFamilies=AF_INET; do
          ${pkgs.gnugrep}/bin/grep -F -x -- "$setting" "$service"
        done
        if ${pkgs.gnugrep}/bin/grep -F -x -- 'RestrictAddressFamilies=AF_INET6' "$service"; then
          exit 1
        fi
        if ${pkgs.gnugrep}/bin/grep -E '^(Environment|EnvironmentFile)=' "$service"; then
          exit 1
        fi
        ${pkgs.systemd}/bin/systemd-analyze verify --user --recursive-errors=no "$service"
        touch "$out"
      '';

    prWardenConfiguration = system: enabled:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        modules = [
          ./modules/agent-deck-pr-warden.nix
          {
            home.username = "warden-check";
            home.homeDirectory = "/home/warden-check";
            home.stateVersion = "24.05";
            programs.agent-deck-pr-warden = {
              enable = enabled;
              runtimeConfig = "/run/warden-check/config.json";
            };
          }
        ];
      };

    prWardenCheck = system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        enabled = prWardenConfiguration system true;
        disabled = prWardenConfiguration system false;
        generation = enabled.activationPackage;
        package = disabled.config.programs.agent-deck-pr-warden.package;
      in
      assert !(disabled.config.programs.agent-deck-pr-warden.enable);
      assert !(disabled.config.systemd.user.services ? agent-deck-pr-warden);
      assert !(disabled.config.systemd.user.timers ? agent-deck-pr-warden);
      pkgs.runCommand "agent-deck-pr-warden-offline-check" { } ''
        export HOME="$TMPDIR/home"
        export XDG_CONFIG_HOME="$HOME/config" XDG_STATE_HOME="$HOME/state" XDG_RUNTIME_DIR="$HOME/run"
        export PYTHONDONTWRITEBYTECODE=1
        mkdir -p "$XDG_RUNTIME_DIR" private_dot_local/bin tests/fixtures/agent_deck_pr_warden \
          nix/modules docs
        chmod 0700 "$HOME" "$XDG_RUNTIME_DIR"
        install -m 0700 \
          ${../private_dot_local/bin/private_executable_agent-deck-pr-warden-controller} \
          private_dot_local/bin/private_executable_agent-deck-pr-warden-controller
        install -m 0600 ${../tests/test_agent_deck_pr_warden_controller.py} \
          tests/test_agent_deck_pr_warden_controller.py
        install -m 0700 ${../tests/fixtures/agent_deck_pr_warden/fake_github_facts.py} \
          tests/fixtures/agent_deck_pr_warden/fake_github_facts.py
        install -m 0600 ${./modules/agent-deck-pr-warden.nix} \
          nix/modules/agent-deck-pr-warden.nix
        install -m 0600 ${../docs/agent-deck-pr-warden.md} docs/agent-deck-pr-warden.md
        ${pkgs.python3}/bin/python3 -m unittest tests.test_agent_deck_pr_warden_controller -v
        "${package}/bin/agent-deck-pr-warden-controller" --help >/dev/null
        mkdir private-runtime
        ${pkgs.coreutils}/bin/install -m 0700 \
          "${package}/libexec/agent-deck-pr-warden-controller.py" \
          private-runtime/controller.py
        test "$(${pkgs.coreutils}/bin/stat -c %a private-runtime/controller.py)" = 700
        service="${generation}/home-files/.config/systemd/user/agent-deck-pr-warden.service"
        timer="${generation}/home-files/.config/systemd/user/agent-deck-pr-warden.timer"
        test -f "$service"
        test -f "$timer"
        ${pkgs.gnugrep}/bin/grep -F -- "install -m 0700" "$service"
        ${pkgs.gnugrep}/bin/grep -F -- "%t/agent-deck-pr-warden/controller.py" "$service"
        for setting in UMask=0077 StateDirectoryMode=0700 RuntimeDirectoryMode=0700 \
          LimitCORE=0 NoNewPrivileges=true ProtectSystem=strict \
          RestrictAddressFamilies=AF_UNIX RestrictRealtime=true RestrictSUIDSGID=true \
          LockPersonality=true SystemCallArchitectures=native; do
          ${pkgs.gnugrep}/bin/grep -F -x -- "$setting" "$service"
        done
        ${pkgs.gnugrep}/bin/grep -F -x -- "OnUnitInactiveSec=5m" "$timer"
        if ${pkgs.gnugrep}/bin/grep -E '^(Environment|EnvironmentFile)=' "$service"; then
          exit 1
        fi
        ${pkgs.systemd}/bin/systemd-analyze verify --user --recursive-errors=no "$service" "$timer"
        touch "$out"
      '';

    archiveOnlyPackage = system:
      import ./lib/agent-deck-archive-only-custodian.nix {
        pkgs = nixpkgs.legacyPackages.${system};
      };

    archiveOnlyConfiguration = system: enabled:
      home-manager.lib.homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.${system};
        modules = [
          ./modules/agent-deck-archive-only-custodian.nix
          {
            home.username = "archive-check";
            home.homeDirectory = "/home/archive-check";
            home.stateVersion = "24.05";
          }
        ] ++ nixpkgs.lib.optional enabled {
          programs.agent-deck-archive-only-custodian.enable = true;
        };
      };

    archiveOnlyCheck = system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        package = archiveOnlyPackage system;
        disabled = (archiveOnlyConfiguration system false).activationPackage;
        enabled = (archiveOnlyConfiguration system true).activationPackage;
      in
      pkgs.runCommand "agent-deck-archive-only-custodian-check" { } ''
        test -x "${package}/bin/agent-deck-archive-only-custodian"
        "${package}/bin/agent-deck-archive-only-custodian" --help >/dev/null
        test ! -e "${disabled}/home-path/bin/agent-deck-archive-only-custodian"
        test -x "${enabled}/home-path/bin/agent-deck-archive-only-custodian"
        for generation in "${disabled}" "${enabled}"; do
          test ! -e "$generation/home-files/.config/systemd/user/agent-deck-archive-only-custodian.service"
          test ! -e "$generation/home-files/.config/systemd/user/agent-deck-archive-only-custodian.timer"
        done
        touch "$out"
      '';

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

    homeManagerModules.agent-deck-archive-only-custodian = ./modules/agent-deck-archive-only-custodian.nix;
    homeManagerModules.agent-deck-pr-warden = ./modules/agent-deck-pr-warden.nix;

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
      x86_64-linux.maintenance-runtime = maintenanceRuntimeCheck "x86_64-linux";
      x86_64-linux.slack-watchdog-runtime = slackWatchdogRuntimeCheck "x86_64-linux";
      x86_64-linux.signed-ingress = signedIngressCheck "x86_64-linux";
      x86_64-linux.pr-warden = prWardenCheck "x86_64-linux";
      x86_64-linux.archive-only-custodian = archiveOnlyCheck "x86_64-linux";
      aarch64-linux.hm-build = self.homeConfigurations."${username}@linux-aarch64".activationPackage;
      aarch64-linux.signed-ingress = signedIngressCheck "aarch64-linux";
    };

    packages = nixpkgs.lib.genAttrs linuxSystems (system: {
      agent-deck-archive-only-custodian = archiveOnlyPackage system;
      agent-deck-pr-warden = (prWardenConfiguration system false).config.programs.agent-deck-pr-warden.package;
      agent-deck-signed-ingress = (signedIngressConfiguration system false).config.programs.agent-deck-signed-ingress.package;
    });

    formatter = nixpkgs.lib.genAttrs ([ "aarch64-darwin" ] ++ linuxSystems)
      (system: nixpkgs.legacyPackages.${system}.nixpkgs-fmt);
  };
}
