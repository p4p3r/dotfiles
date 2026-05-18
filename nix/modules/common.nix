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
    semgrep
    terraform-docs
    clang-tools
  ] ++ lib.optionals pkgs.stdenv.isLinux [
    # Docker CLI on Linux only (macOS uses Orbstack, which provides both
    # `docker` and `docker compose`). The `docker` package ships both
    # `docker` (client) and `dockerd` (daemon) binaries. We only need the
    # client here — the daemon must run as a system service, which
    # home-manager can't manage (no root + systemd-system access). The
    # daemon is installed via the `installSystemPackagesLinux` activation
    # block below (apt install docker.io).
    docker

    # docker-compose v2 (Go-based plugin) — Orbstack ships this on Mac at
    # ~/.docker/cli-plugins/docker-compose, so `docker compose` works there.
    # On Linux we install via nix + symlink into the same CLI-plugins dir
    # in the activation block below, so the same `docker compose` UX works.
    docker-compose
  ]);

  home.sessionPath = [ "$HOME/.local/bin" "$HOME/.npm-global/bin" "$HOME/.opencode/bin" ];

  # ----------------------------------------------------------------------------
  # Linux nix config + auto-gc.
  # Mac equivalents live in nix/modules/nix-settings.nix (only loaded by
  # mkDarwin in flake.nix). On Linux:
  #   - System-level /etc/nix/nix.conf (substituters, public keys, experimental
  #     features, keep-outputs) is written by installSystemPackagesLinux below.
  #     System-level matches nix-darwin's `nix.settings` placement on Mac and
  #     avoids polluting ~/.config/nix/ (which is symlinked into the dotfiles
  #     repo on the devbox, so an xdg.configFile entry would materialize a
  #     stray symlink inside the working tree).
  #   - User must be in `trusted-users` in /etc/nix/nix.conf for client-set
  #     options to apply. user_data.sh Phase 12.5 handles that at instance
  #     boot; not the user's responsibility post-bootstrap.
  #   - systemd user timer for `nix-collect-garbage` (parity with the launchd
  #     job nix-darwin installs from `nix.gc.automatic = true`).
  # ----------------------------------------------------------------------------

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

      # docker-compose v2 plugin wiring — nix installs the binary at
      # ~/.nix-profile/bin/docker-compose. Docker CLI v2 also looks for
      # plugins at ~/.docker/cli-plugins/<name>, where `<name>` becomes
      # the `docker <name>` subcommand. Mirror Orbstack's macOS layout by
      # symlinking the nix binary there so `docker compose ...` works,
      # not just the standalone `docker-compose ...`.
      mkdir -p "$HOME/.docker/cli-plugins"
      if [ ! -L "$HOME/.docker/cli-plugins/docker-compose" ] \
         || [ ! -x "$HOME/.docker/cli-plugins/docker-compose" ]; then
        if command -v docker-compose >/dev/null 2>&1; then
          ln -sf "$(command -v docker-compose)" "$HOME/.docker/cli-plugins/docker-compose"
        fi
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

    # System-level packages on Ubuntu — things home-manager can't manage on
    # non-NixOS Linux (services, /etc/, system-wide binaries that need root).
    # Mirrors what nix-darwin's `homebrew.brews` covers on macOS.
    #
    # Requires NOPASSWD sudo: the devbox user_data grants this; on other
    # Ubuntu hosts run `sudo visudo` first. `sudo -n` makes this fail fast
    # rather than hanging on a password prompt.
    #
    # Each step is idempotent — re-running on `nix_switch` is a no-op once
    # the package/service/group state is already correct.
    installSystemPackagesLinux = lib.hm.dag.entryAfter [ "installUpstreamClis" ] ''
      # System binaries live at /usr/bin and /bin on Ubuntu — home-manager
      # activation gets a scrubbed PATH (mostly nix store), so we need to
      # prepend the system paths explicitly to find sudo/apt-get/dpkg/etc.
      export PATH=${pkgs.coreutils}/bin:${pkgs.gnugrep}/bin:${pkgs.systemd}/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH

      if ! sudo -n true 2>/dev/null; then
        echo "[postActivation] WARN: no NOPASSWD sudo — skipping system package install."
        echo "                  (docker daemon, etc. will not be set up. Configure"
        echo "                   sudoers or install them manually with apt.)"
        exit 0
      fi

      # Docker daemon (CLI comes from pkgs-unstable via home.packages). On
      # macOS we use Orbstack; Linux has no equivalent abstraction here.
      if ! dpkg -s docker.io >/dev/null 2>&1; then
        echo "[postActivation] Installing docker.io via apt…"
        sudo -n apt-get update -qq
        sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io \
          || echo "[postActivation] WARN: docker.io install failed (non-fatal)"
      fi
      if dpkg -s docker.io >/dev/null 2>&1; then
        if ! sudo -n systemctl is-enabled --quiet docker 2>/dev/null; then
          echo "[postActivation] Enabling docker.service…"
          sudo -n systemctl enable --now docker || true
        fi
        if ! id -nG "$USER" 2>/dev/null | grep -qw docker; then
          echo "[postActivation] Adding $USER to docker group (requires re-login to take effect)…"
          sudo -n usermod -aG docker "$USER" || true
        fi
      fi

      # /etc/nix/nix.conf: substituters + trusted-public-keys + experimental
      # features + keep-{outputs,derivations}. Lives at SYSTEM level (matches
      # nix-darwin's `nix.settings`) so the daemon honors them directly
      # instead of needing `trusted-users` to forward user-level overrides.
      # Wrapped in a marker block — re-runs of this activation step replace
      # the block atomically rather than appending duplicates.
      NIXCONF=/etc/nix/nix.conf
      MARKER_START='# >>> managed by home-manager installSystemPackagesLinux >>>'
      MARKER_END='# <<< managed by home-manager installSystemPackagesLinux <<<'
      if [ -f "$NIXCONF" ]; then
        # Strip any existing managed block.
        sudo -n sed -i.bak "/$MARKER_START/,/$MARKER_END/d" "$NIXCONF" 2>/dev/null || true
        sudo -n rm -f "$NIXCONF.bak"
      else
        sudo -n mkdir -p /etc/nix
        sudo -n touch "$NIXCONF"
      fi
      # Append fresh block. `tee -a` works under sudo without needing a
      # subshell redirect.
      sudo -n tee -a "$NIXCONF" >/dev/null <<EOF
$MARKER_START
experimental-features = nix-command flakes
keep-outputs = true
keep-derivations = true
extra-substituters = https://nix-community.cachix.org https://devenv.cachix.org
extra-trusted-public-keys = nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs= devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw=
$MARKER_END
EOF
      # Reload the daemon so the new config takes effect for subsequent
      # nix invocations. is-active check avoids a spurious "Unit not found"
      # error during very first activation before nix-daemon is installed.
      if sudo -n systemctl is-active --quiet nix-daemon.service 2>/dev/null; then
        sudo -n systemctl restart nix-daemon.service || true
      fi
    '';
  };
}
