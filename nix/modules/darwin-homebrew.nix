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

      # Graphite
      "withgraphite/tap"

      # Agent Deck (AI agent session manager)
      "asheshgoplani/tap"

      # Others
      "koekeishiya/formulae"
      "nikitabobko/tap"
      "FelixKratz/formulae"
      "cirruslabs/cli"
    ];

    brews = [
      "koekeishiya/formulae/skhd"
      "withgraphite/tap/graphite"
      "osx-cross/arm/arm-gcc-bin@10"
      "qmk/qmk/hid_bootloader_cli"
      "qmk/qmk/qmk"
      "avrdude"
      "dfu-util"
      "teensy_loader_cli"
      "dfu-programmer"
      "mdloader"
      "sketchybar"
      "cirruslabs/cli/tart"
      "softnet"
      "asheshgoplani/tap/agent-deck"
      "clang-format"
      "make"
      "ripgrep"
      "semgrep"
      "terraform-docs"
      "tmux"
    ];

    casks = [
      "1password"
      "aerospace"
      "audacity"
      "balenaetcher"
      "brave-browser"
      "aws-vpn-client"
      "claude-island"
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
      "linear-linear"
      "little-snitch"
      "notion"
      "obs"
      "orbstack"
      "pearcleaner"
      "pgadmin4"
      "presonus-universal-control"
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
    };

    onActivation = {
      autoUpdate = true;
      cleanup = "zap";
    };
  };
}
