{ config, pkgs, lib, inputs, ... }:
{
  imports = [ inputs.nix-homebrew.darwinModules.nix-homebrew ];

  nix-homebrew = {
    enable = true;
    user = builtins.getEnv "USER";
    autoMigrate = true;
  };

  homebrew = {
    enable = true;

    taps = [
      # QMK
      "osx-cross/arm"
      "osx-cross/avr"
      "qmk/qmk"

      # Agent Deck (AI agent session manager)
      "asheshgoplani/tap"

      # Others
      # Pinned to an explicit URL, NOT the "koekeishiya/..." shorthand.
      # The skhd/yabai author renamed their GitHub account koekeishiya ->
      # asmvik, so github.com/koekeishiya/homebrew-formulae only reaches the
      # real repo via GitHub's rename redirect. A different account has since
      # taken the freed "koekeishiya" username (created 2025-12-09), and that
      # redirect stops working the moment they create a repo of the same name
      # — at which point the shorthand would silently tap THEIR repo. Pinning
      # the resolved URL removes the redirect from the trust path entirely.
      { name = "koekeishiya/formulae";
        clone_target = "https://github.com/asmvik/homebrew-formulae.git"; }
      "nikitabobko/tap"
      "FelixKratz/formulae"
      "cirruslabs/cli"
    ];

    brews = [
      "koekeishiya/formulae/skhd"
      "osx-cross/arm/arm-gcc-bin@10"
      "qmk/qmk/hid_bootloader_cli"
      "qmk/qmk/qmk"
      "avrdude"
      "dfu-util"
      # Declared so `cleanup = "zap"` cannot remove it: mas is the package
      # manager behind masApps below, and brew bundle aborts without it.
      "mas"
      "teensy_loader_cli"
      "dfu-programmer"
      "mdloader"
      "sketchybar"
      "cirruslabs/cli/tart"
      "softnet"
      "asheshgoplani/tap/agent-deck"
      "mutagen-io/mutagen/mutagen"
      # pipx: provisions PyPI CLI tools into ~/.local/bin. Sourced from brew
      # (not nix) on purpose: brew's Python is stable across nix rebuilds, so
      # pipx venvs don't get orphaned when a nix-store Python path changes.
      "pipx"
      # Cross-platform tools (make, node, ripgrep, tmux) now via nix in
      # nix/modules/common.nix. graphite/terraform-docs/clang-format via
      # pkgs-unstable in same file. pup installed from GitHub releases in
      # flake.nix postActivation (Mac) + common.nix activation (Linux).
    ];

    casks = [
      "1password"
      "aerospace"
      "audacity"
      "balenaetcher"
      "brave-browser"
      "aws-vpn-client"
      "vibe-notch"
      # codex CLI is installed via npm (@openai/codex) in flake.nix activation
      "conductor"
      "cursor"
      "emdash"
      "font-fira-code-nerd-font"
      "font-fira-mono-for-powerline"
      "font-hack-nerd-font"
      "font-meslo-lg-nerd-font"
      "font-source-code-pro"
      "ghostty"
      "git-credential-manager"
      "google-chrome"
      "google-drive"
      "keka"
      "linear"
      "little-snitch"
      "nextcloud"
      "notion"
      "obs"
      "orbstack"
      "pearcleaner"
      "pgadmin4"
      "fender-universal-control"
      "obsidian"
      "qmk-toolbox"
      "raindropio"
      "raycast"
      "setapp"
      "shottr"
      "signal"
      "slack"
      "sonos"
      "superset"
      "stats"
      "switchresx"
      "visual-studio-code"
      "visual-studio-code@insiders"
      "vlc"
      "whatsapp"
      "wireshark-app"
      "zen"
    ];

    masApps = {
      "1Password for Safari" = 1569813296;
      "CARROT Weather" = 993487541;
      "DaisyDisk" = 411643860;
      "Fantastical" = 975937182;
      "1Blocker" = 1365531024;
      "Save to Raindrop.io" = 1549370672;
      "Wireguard" = 1451685025;
    };

    onActivation = {
      # MUST stay false, or every activation fails on the Mac App Store apps.
      # brew's auto-update re-executes brew, and the re-exec loses
      # /opt/homebrew/bin from the PATH that ORIGINAL_PATHS is built from. mas
      # lives there, so `which("mas", ORIGINAL_PATHS)` comes back nil,
      # ensure_package_manager_installed! decides mas is missing, runs
      # `brew install --formula mas`, gets "already installed", and raises
      # against the FIRST mas entry in the Brewfile — which is why this
      # surfaced for years as the misleading "Unable to install 1Blocker app".
      # Verified: same Brewfile fails with auto-update on, exits 0 with
      # HOMEBREW_NO_AUTO_UPDATE=1 (which is exactly what autoUpdate=false sets).
      # Little is lost: brew is nix-managed and cannot self-update, so this
      # only skipped refreshing tap/API metadata. Run `brew update` by hand.
      autoUpdate = false;
      # Run installs but skip the in-place upgrade pass, so a switch never
      # silently upgrades formulae or casks. Note this does NOT govern Mac App
      # Store apps: brew's install_batch! ignores no_upgrade and always runs
      # `mas upgrade` for installed apps. Manual `brew upgrade` still works.
      upgrade = false;
      cleanup = "zap";
    };
  };
}
