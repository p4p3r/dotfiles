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
      "sketchybar"
      "cirruslabs/cli/tart"

      # Global development tools
      "node"          # Provides npm and npx
      "python@3.12"   # Provides pip
      "pipx"          # Python CLI tools in isolated environments
      "semgrep"       # Static analysis tool
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
      "linear-linear"
      "little-snitch"
      "notion"
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
      "slack"
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
    };

    onActivation = {
      autoUpdate = true;
      cleanup = "zap";
    };
  };
}
