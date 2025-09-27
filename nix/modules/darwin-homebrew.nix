{ config, pkgs, lib, ... }:
{
  imports = [ (builtins.getFlake (toString ../../.).inputs.nix-homebrew.darwinModules.nix-homebrew) ];

  nix-homebrew = {
    enable = true;
    user = builtins.getEnv "USER";
    autoMigrate = true;
  };

  homebrew = {
    enable = true;

    taps = [
      "homebrew/bundle"
      "homebrew/cask"
      "homebrew/core"
      "homebrew/services"

      # QMK
      "osx-cross/arm"
      "osx-cross/avr"
      "qmk/qmk"

      # Graphite
      withgraphite/tap

      # Others
      "koekeishiya/formulae"
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
    ];

    casks = [ 
      "1password"
      "1password-cli"
      "amethyst"
      "audacity"
      "balenaetcher"
      "brave-browser"
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
      "linear-linear"
      "little-snitch"
      "notion"
      "obs"
      "orbstack"
      "pgadmin4"
      "qmk-toolbox"
      "raindropio"
      "raycast"
      "setapp"
      "signal"
      "slack"
      "sonos"
      "visual-studio-code"
      "visual-studio-code@insiders"
      "vlc"
      "warp"
      "whatsapp"
      "wireshark-app"
    ];

    masApps = {
      "1Password for Safari" = 1569813296;
      "CARROTweather" = 993487541;
      "DaisyDisk" = 411643860;
      "Fantastical" = 975937182;
      "Keynote" = 409183694;
      "Numbers" = 409203825;
      "Okta Verify" = 490179405;
      "Pages" = 409201541;
      "Xcode" = 497799835;  };

    onActivation = {
      autoUpdate = true;
      cleanup = "zap";
    };
  };
}
