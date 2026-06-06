{ pkgs, pkgs-unstable, ... }:

{
  # Default development toolchain. Available in $HOME when not inside a
  # project-specific direnv.
  #
  # Use `pkgs.X` for things that should track 25.11 stable and `pkgs-unstable.X`
  # for tools you want bleeding-edge. Refresh unstable with
  # `nix flake update nixpkgs-unstable` from this directory.
  packages =
    (with pkgs; [
      # Build essentials
      gnumake
      cmake
      pkg-config

      # Node.js
      nodejs_22
      corepack

      # Python
      python312
      python312Packages.pip
      python312Packages.virtualenv
      pipx

      # Rust
      rustup
    ])
    ++ (with pkgs-unstable; [
      uv
    ]);
}
