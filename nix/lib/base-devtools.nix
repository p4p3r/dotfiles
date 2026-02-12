# lib/base-devtools.nix
# Base development tools - common utilities only
# Language-specific toolchains are managed per-project via devenv
{ pkgs }:

builtins.filter (x: x != null) (with pkgs; [
  # Version control & collaboration
  git
  gh
  git-lfs
  lazygit

  # Core dev utilities
  jq
  yq
  curl
  wget

  # Build essentials (basic only)
  gnumake
  pkg-config

  # Common dev QoL tools
  pre-commit
])
