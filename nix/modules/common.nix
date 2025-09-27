{ config, pkgs, lib, ... }:
let
  devPkgs = import ../lib/devtoolchain.nix { inherit pkgs; };
  jdk = if pkgs ? jdk21 then pkgs.jdk21 else pkgs.jdk;
in {
  home.stateVersion = "24.05";
  programs.home-manager.enable = true;

  programs.fish = {
    enable = true;
    shellInit = ''
      # 1Password SSH agent (auto-detect)
      if test (uname) = "Darwin"
        set -l sock "$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
        if test -S "$sock"; set -gx SSH_AUTH_SOCK "$sock"; end
      else
        if test -n "$XDG_RUNTIME_DIR"
          set -l sock "$XDG_RUNTIME_DIR/1password/agent.sock"
          if test -S "$sock"; set -gx SSH_AUTH_SOCK "$sock"; end
        end
        if not set -q SSH_AUTH_SOCK
          for sock in "$HOME/.1password/agent.sock" "$HOME/.config/1Password/ssh/agent.sock"
            if test -S "$sock"; set -gx SSH_AUTH_SOCK "$sock"; break; end
          end
        end
      end
      # Enable Node corepack (yarn/pnpm shims)
      if type -q corepack
        corepack enable >/dev/null ^ /dev/null
      end
    '';
  };

  # Toolchains & dev essentials
  home.packages = devPkgs ++ (with pkgs; [
    # Essentials
    _1password-cli chezmoi gnupg openssl wget curl
    coreutils findutils gnused gnugrep gawk patch yq-go jq

    # Shell
    fish zsh starship zellij tmux

    # Developer quality-of-life
    neovim ripgrep fd bat fzf delta eza
    jq yq-go tealdeer tree vbindiff rename lsof
    nodePackages.prettier lazygit claude-code

    # Various tools
    lesspipe openssh imagemagick graphviz
    tesseract

    # Network
    nmap socat tcpdump netcat-gnu

    # k8s / devops
    kubectl kubernetes-helm kustomize terraform awscli2 k9s
  ] ++ lib.optionals pkgs.stdenv.isDarwin [
    pinentry_mac
  ] ++ lib.optionals pkgs.stdenv.isLinux [
    pinentry
  ]);

  home.sessionVariables.JAVA_HOME = "${jdk}/lib/openjdk";
  home.sessionPath = [ "$HOME/.local/bin" ];
}
