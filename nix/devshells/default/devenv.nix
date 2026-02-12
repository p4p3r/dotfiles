{ pkgs, ... }:

{
  # Default development toolchain
  # Available in $HOME when not inside a project-specific direnv
  packages = with pkgs; [
    # Build essentials
    gnumake
    cmake
    pkg-config

    # Node.js
    nodejs_20
    corepack

    # Python
    python312
    python312Packages.pip
    python312Packages.virtualenv
    pipx

    # Rust
    rustup
  ];
}
