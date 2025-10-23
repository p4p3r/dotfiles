{ config, pkgs, ... }: {
  # # Extra mac-only packages for this machine
  # home.packages = with pkgs; [ cocoapods ];
  #
  # # macOS defaults just for this host
  # system.defaults.NSGlobalDomain."AppleInterfaceStyle" = "Dark";
  #
  # # Extra Homebrew GUI apps just for this Mac
  # homebrew.casks = (config.homebrew.casks or []) ++ [ "cleanclip" ];
}
