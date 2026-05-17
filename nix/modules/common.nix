{ config, pkgs, pkgs-unstable, lib, ... }:
let
  baseDevPkgs = import ../lib/base-devtools.nix { inherit pkgs; };
in {
  home.stateVersion = "24.05";
  programs.home-manager.enable = true;

  # Import shell configuration
  imports = [
    ./shell/fish.nix
  ];

  # Configure direnv for automatic devenv loading
  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  # Base toolchains & dev essentials.
  # Convention:
  #   - `pkgs.X`         → 25.11 stable. Stable across devenv projects too.
  #     Use for everything where reproducibility matters more than version freshness.
  #   - `pkgs-unstable.X` → rolling nixos-unstable. Use for CLIs you want close
  #     to upstream HEAD. Refresh with `nix_update nixpkgs-unstable && nix_switch`.
  home.packages = baseDevPkgs ++ (with pkgs; [
    # devenv for per-project development environments
    devenv nil nixfmt

    # Essentials
    _1password-cli chezmoi gnupg openssl wget curl
    coreutils findutils gnused gnugrep gawk patch jq

    # Shell
    fish zsh starship zellij tmux

    # Developer quality-of-life
    git-lfs neovim ripgrep fd bat fzf delta eza
    tealdeer tree vbindiff rename lsof
    nodePackages.prettier lazygit sqlitebrowser

    # Various tools
    lesspipe openssh imagemagick graphviz
    tesseract

    # Network
    nmap socat tcpdump netcat-gnu

    # k8s / devops
    kubectl kubernetes-helm kustomize terraform awscli2 k9s
    argocd argo-workflows kubectx stern

  ] ++ lib.optionals pkgs.stdenv.isDarwin [
    pinentry_mac
  ] ++ lib.optionals pkgs.stdenv.isLinux [
    pinentry-curses    # `pinentry` was removed in nixpkgs 25.11; pick a variant
  ]) ++ (with pkgs-unstable; [
    # Tools we want bleeding-edge — sourced from nixos-unstable rather than the
    # 25.11 stable channel.
    graphite-cli
    REDACTED
    terraform-docs
    clang-tools
  ] ++ lib.optionals pkgs.stdenv.isLinux [
    # Docker CLI on Linux only (macOS uses Orbstack). The `docker` package
    # ships both `docker` (client) and `dockerd` (daemon) binaries. We only
    # need the client here — the daemon must run as a system service, which
    # home-manager can't manage (no root + systemd-system access). Install
    # the daemon at the system level (e.g. via user_data.sh on the devbox)
    # and add the user to the `docker` group so the client can talk to
    # /var/run/docker.sock without sudo.
    docker
  ]);

  home.sessionPath = [ "$HOME/.local/bin" "$HOME/.npm-global/bin" "$HOME/.opencode/bin" ];

  # ----------------------------------------------------------------------------
  # Linux nix config + auto-gc.
  # Mac equivalents live in nix/modules/nix-settings.nix (only loaded by
  # mkDarwin in flake.nix). On Linux we drive nix via home-manager:
  #   - user-level ~/.config/nix/nix.conf for substituters (binary caches)
  #   - systemd user timer for `nix-collect-garbage` (parity with the launchd
  #     job nix-darwin installs from `nix.gc.automatic = true`)
  # Note: for substituters to actually be honored, the user must be in
  # `trusted-users` in /etc/nix/nix.conf (system-level). On the devbox this is
  # handled by user_data.sh during instance bootstrap.
  # ----------------------------------------------------------------------------
  xdg.configFile = lib.mkIf pkgs.stdenv.isLinux {
    "nix/nix.conf".text = ''
      experimental-features = nix-command flakes
      keep-outputs = true
      keep-derivations = true
      substituters = https://cache.nixos.org https://nix-community.cachix.org https://devenv.cachix.org
      trusted-public-keys = cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY= nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs= devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw=
    '';
  };

  systemd.user.services = lib.mkIf pkgs.stdenv.isLinux {
    nix-gc = {
      Unit.Description = "Nix garbage collection (--delete-older-than 30d)";
      Service = {
        Type = "oneshot";
        ExecStart = "${pkgs.nix}/bin/nix-collect-garbage --delete-older-than 30d";
      };
    };
  };

  systemd.user.timers = lib.mkIf pkgs.stdenv.isLinux {
    nix-gc = {
      Unit.Description = "Weekly nix garbage collection";
      Timer = {
        OnCalendar = "weekly";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };

  # Linux-side equivalent of the nix-darwin `system.activationScripts.postActivation`
  # block in flake.nix. nix-darwin's hook is darwin-only — on Linux we run the
  # same npm globals + claude/opencode installers from home-manager activation
  # so the same upstream-managed CLIs end up under ~/.local/bin, ~/.npm-global/bin,
  # ~/.opencode/bin (all of which are already in sessionPath above).
  home.activation = lib.mkIf pkgs.stdenv.isLinux {
    installUpstreamClis = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      # opencode's installer extracts a tarball, so tar/gzip must be on PATH.
      export PATH=${pkgs.nodejs_22}/bin:${pkgs.curl}/bin:${pkgs.bash}/bin:${pkgs.gnutar}/bin:${pkgs.gzip}/bin:$PATH
      export NPM_CONFIG_PREFIX="$HOME/.npm-global"
      mkdir -p "$NPM_CONFIG_PREFIX" "$HOME/.local/bin"

      echo "[postActivation] Installing global npm packages…"
      npm install -g @openai/codex             || true
      npm install -g @zed-industries/codex-acp || true
      npm install -g @agentclientprotocol/claude-agent-acp || true

      if [ ! -x "$HOME/.local/bin/claude" ]; then
        echo "[postActivation] Installing Claude Code (native installer)…"
        curl -fsSL https://claude.ai/install.sh | bash || true
      fi

      if [ ! -x "$HOME/.opencode/bin/opencode" ]; then
        echo "[postActivation] Installing opencode…"
        curl -fsSL https://opencode.ai/install | bash || true
      fi

      # agent-deck — Linux equivalent of the asheshgoplani/tap/agent-deck
      # Homebrew cask we use on macOS. Use the upstream install script.
      if [ ! -x "$HOME/.local/bin/agent-deck" ]; then
        echo "[postActivation] Installing agent-deck (upstream install.sh)…"
        curl -fsSL https://raw.githubusercontent.com/asheshgoplani/agent-deck/main/install.sh | bash \
          || echo "[postActivation] WARN: agent-deck install failed (non-fatal)"
      fi

      # pup (Datadog) — installed from GitHub releases. README lists brew,
      # cargo, or manual download; no upstream install script. Fetch latest
      # tarball, extract binary into ~/.local/bin/pup.
      if [ ! -x "$HOME/.local/bin/pup" ]; then
        echo "[postActivation] Installing pup (DataDog/pup latest release)…"
        pup_ver="$(curl -fsSL https://api.github.com/repos/DataDog/pup/releases/latest \
          | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -1)"
        if [ -n "$pup_ver" ]; then
          arch="$(uname -m)"
          case "$arch" in
            aarch64|arm64) pup_arch="arm64" ;;
            x86_64)        pup_arch="x86_64" ;;
            *)             pup_arch="$arch" ;;
          esac
          url="https://github.com/DataDog/pup/releases/download/v$pup_ver/pup_''${pup_ver}_Linux_''${pup_arch}.tar.gz"
          curl -fsSL "$url" | tar -xzC "$HOME/.local/bin" pup \
            || echo "[postActivation] WARN: pup install failed (non-fatal)"
        else
          echo "[postActivation] WARN: could not resolve pup latest version"
        fi
      fi
    '';
  };
}
