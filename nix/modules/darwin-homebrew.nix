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
    ];

    casks = [
      "1password"
      "aerospace"
      "audacity"
      "balenaetcher"
      "brave-browser"
      "claude-code"
      "codex"
      "cryptomator"
      "cursor"
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
      "little-snitch"
      "obs"
      "orbstack"
      "pearcleaner"
      "pgadmin4"
      "presonus-universal-control"
      "qmk-toolbox"
      "raindropio"
      "raycast"
      "setapp"
      "shottr"
      "signal"
      "sonos"
      "stats"
      "switchresx"
      "visual-studio-code"
      "visual-studio-code@insiders"
      "vlc"
      "warp"
      "whatsapp"
      "wireshark-app"
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
