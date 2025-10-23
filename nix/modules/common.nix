{ config, pkgs, lib, ... }:
let
  devPkgs = import ../lib/devtoolchain.nix { inherit pkgs; };
  jdk = if pkgs ? jdk21 then pkgs.jdk21 else pkgs.jdk;
in {
  home.stateVersion = "24.05";
  programs.home-manager.enable = true;

  # Fish config is managed by chezmoi; home-manager just ensures fish is available
  # programs.fish.enable would create ~/.config/fish/config.fish and conflict with chezmoi
  # Instead, the fish config from chezmoi will source nix-managed paths via the shell setup

  # Toolchains & dev essentials
  home.packages = devPkgs ++ (with pkgs; [
    # Essentials
    _1password-cli chezmoi gnupg openssl wget curl
    coreutils findutils gnused gnugrep gawk patch jq

    # Shell
    fish zsh starship zellij tmux

    # Developer quality-of-life
    neovim ripgrep fd bat fzf delta eza
    tealdeer tree vbindiff rename lsof
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
