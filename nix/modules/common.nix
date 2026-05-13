{ config, pkgs, lib, ... }:
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

  # Base toolchains & dev essentials
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
    argocd argo kubectx stern

  ] ++ lib.optionals pkgs.stdenv.isDarwin [
    pinentry_mac
  ] ++ lib.optionals pkgs.stdenv.isLinux [
    pinentry
  ]);

  home.sessionPath = [ "$HOME/.local/bin" "$HOME/.npm-global/bin" "$HOME/.opencode/bin" ];

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
      mkdir -p "$NPM_CONFIG_PREFIX"

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
    '';
  };
}
