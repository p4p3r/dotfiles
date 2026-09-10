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
      # skhd/yabai, referenced by the author's CURRENT account name asmvik.
      # They renamed koekeishiya -> asmvik, so the old name only resolved via
      # GitHub's rename redirect, and a different account has since taken the
      # freed old username (created 2025-12-09). If that account ever creates
      # homebrew-formulae the redirect dies and the old shorthand would
      # silently tap THEIRS. Naming the real owner needs no clone_target and
      # leaves no squattable name anywhere in this config.
      "asmvik/formulae"
      "nikitabobko/tap"
      "FelixKratz/formulae"
      "cirruslabs/cli"
    ];

    brews = [
      "asmvik/formulae/skhd"
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

      # Declared because brew is their ONLY source in a plain login shell.
      # nix has them, but only inside the devenv/devtoolchain devshells
      # (nix/devshells/default/devenv.nix, nix/lib/devtoolchain.nix), not in
      # home-manager — so outside a direnv-activated shell these come from
      # brew. Verified against a bare login PATH.
      "cmake"
      "node"
      "pkgconf"
      # Not packaged in this config's nix at all.
      "trufflehog"
      # nixpkgs has it, but brew's macOS packaging of wg-quick/wireguard-go is
      # the better-tested one here.
      "wireguard-tools"

      # ripgrep, terraform-docs and graphite-cli are in home-manager
      # (nix/modules/common.nix, the latter two via pkgs-unstable), so they
      # resolve from /etc/profiles/per-user even with no devshell active. Their
      # brew copies were removed as duplicates. make/tmux likewise via nix. pup
      # installed from GitHub releases in flake.nix postActivation (Mac) +
      # common.nix activation (Linux).
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
      # Installed but previously undeclared, which meant `cleanup` would have
      # deleted them. Apple stock apps plus Amphetamine.
      "Amphetamine" = 937984704;
      "GarageBand" = 682658836;
      "iMovie" = 408981434;
      "Keynote" = 409183694;
      "Numbers" = 409203825;
      "Pages" = 409201541;
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
      # Re-enabled now that the Brewfile matches reality: `brew bundle
      # cleanup` proposes no uninstalls and no untaps, only cache pruning.
      # It was "none" for a while because Homebrew 6 deprecated the switch
      # (it previews rather than removes, and exits non-zero), and because the
      # preview then wanted to delete 25 formulae, 6 Mac App Store apps and 3
      # taps that were installed but undeclared. Before touching this, run
      # `brew bundle cleanup` WITHOUT --force and read what it proposes.
      cleanup = "zap";
    };
  };
}
