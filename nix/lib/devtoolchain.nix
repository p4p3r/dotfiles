# Returns the list of dev packages given a pkgs set.
{ pkgs }:
with pkgs; [
# Essentials
  git git-lfs gh yq jq

  # C / C++
  llvmPackages.latest.clang
  llvmPackages.latest.lldb
  cmake ninja gnumake pkg-config

  # Node / TS
  nodejs_20
  corepack
  nodePackages.typescript
  nodePackages.typescript-language-server
  nodePackages.eslint
  nodePackages.pnpm
  nodePackages.yarn

  # Rust
  rustup rust-analyzer cargo clippy

  # Python
  python312
  python312Packages.pip
  python312Packages.virtualenv
  pipx
  ruff
  pyright
  uv

  # Java / JVM
  temurin-jdk-21 maven gradle

  # Scala
  scala sbt sbt-extras

  # Kotlin
  kotlin

  # OCaml
  ocaml opam dune_3 ocamlformat ocamlPackages.utop
]
