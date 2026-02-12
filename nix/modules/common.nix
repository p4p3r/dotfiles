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

  ] ++ lib.optionals pkgs.stdenv.isDarwin [
    pinentry_mac
  ] ++ lib.optionals pkgs.stdenv.isLinux [
    pinentry
  ]);

  home.sessionPath = [ "$HOME/.local/bin" ];
}
