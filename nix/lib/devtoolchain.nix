# nix/lib/devtoolchain.nix
{ pkgs }:
let
  # Pick an LLVM set available on 25.05; fall back gracefully.
  llvm =
    if pkgs ? llvmPackages_18 then pkgs.llvmPackages_18
    else if pkgs ? llvmPackages_19 then pkgs.llvmPackages_19
    else pkgs.llvmPackages;

  # JDK on 25.05: temurin attrnames vary; use jdk21 if present, else jdk.
  jdk =
    if pkgs ? jdk21 then pkgs.jdk21
    else pkgs.jdk;

  nodeExtras = [
    # nodePackages was removed in nixpkgs 26.05 and now throws rather than
    # being a missing attribute, so `or null` no longer guards it. These all
    # exist at the top level instead.
    (pkgs.typescript-language-server or null)
    (pkgs.eslint or null)
    (pkgs.typescript or null)
  ];
in
builtins.filter (x: x != null) (with pkgs; [
  git gh yq jq
  llvm.clang
  llvm.lldb
  cmake ninja gnumake pkg-config

  nodejs_20
  corepack              # enable pnpm/yarn via: corepack enable

  rustup

  python312 python312Packages.pip python312Packages.virtualenv pipx ruff pyright

  jdk maven gradle
  scala sbt
  kotlin

  ocaml opam dune_3 ocamlformat ocamlPackages.utop
] ++ nodeExtras)

