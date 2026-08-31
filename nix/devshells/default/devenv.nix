{ pkgs, pkgs-unstable, ... }:

let
  slackCutover = builtins.all (name: builtins.getEnv name != "") [
    "SLACK_BOT_TOKEN"
    "SLACK_APP_TOKEN"
    "SLACK_DECK_CHANNEL"
    "SLACK_DECK_USER"
  ];
in
{
  # Default development toolchain. Available in $HOME when not inside a
  # project-specific direnv.
  #
  # Use `pkgs.X` for things that should track 25.11 stable and `pkgs-unstable.X`
  # for tools you want bleeding-edge. Refresh unstable with
  # `nix flake update nixpkgs-unstable` from this directory.

  # Nix's pythons ship a PEP 668 EXTERNALLY-MANAGED marker, so `pip install`
  # refuses to touch them. agent-deck's `conductor setup` shells out to
  # `python3 -m pip install --user toml aiogram` and gates the Telegram bridge
  # daemon on that command exiting 0. Because those libs are already wired into
  # the interpreter above (via withPackages), pip reports "already satisfied"
  # and writes nothing — we just need it to stop refusing on the marker. This
  # env var does exactly that, turning the install into a clean no-op so the
  # daemon installs against our Nix interpreter.
  env.PIP_BREAK_SYSTEM_PACKAGES = "1";

  packages =
    (with pkgs; [
      # Build essentials
      gnumake
      cmake
      pkg-config

      # Genealogy/document research
      ghostscript
      poppler-utils
      imagemagick
      exiftool
      tesseract
      sqlite

      # Node.js
      nodejs_22
      corepack

      # Python — bundle libs INTO the interpreter via withPackages. Listing
      # python312Packages.* as bare entries only drops their store paths in the
      # env; the python312 interpreter never adds them to its sys.path, so
      # `import toml` / `import aiogram` and `python3 -m pip` all fail with
      # ModuleNotFoundError. withPackages produces a single python3 whose
      # site-packages (and pip) are wired in. agent-deck's conductor bridge
      # imports toml plus the configured remote-channel SDKs, and its setup
      # shells out to `python3 -m pip install`, so these must live inside the
      # interpreter. openpyxl/pillow/pyyaml are the genealogy research tools.
      (python312.withPackages (ps: [
        ps.pip
        ps.virtualenv
        ps.toml
        ps.openpyxl
        ps.pillow
        ps.pyyaml
      ] ++ pkgs.lib.optionals slackCutover [
        ps.slack-bolt
        ps.slack-sdk
        ps.aiohttp
      ] ++ pkgs.lib.optionals (!slackCutover) [
        ps.aiogram
      ]))
      pipx

      # Rust
      rustup
    ])
    ++ (with pkgs-unstable; [
      uv

      # Go toolchain (bleeding-edge to match modern Go projects like agent-deck,
      # which builds against a recent Go). Added 2026-06-09 so `go`/`gofmt` are
      # available in the default $HOME devenv instead of ad-hoc
      # `nix shell nixpkgs#go`. `gotools` provides goimports etc.
      go
      gotools
    ]);
}
