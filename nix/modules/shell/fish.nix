{ config, pkgs, lib, ... }:

{
  # Minimal Fish configuration - just add direnv hook
  # Main Fish config is managed by chezmoi to allow applications to modify it
  # This only adds the essential direnv integration for devenv support

  # Add direnv hook to Fish
  home.file.".config/fish/conf.d/00-direnv.fish".text = ''
    # Direnv hook for Fish (managed by Nix)
    # This enables automatic devenv loading in project directories
    ${pkgs.direnv}/bin/direnv hook fish | source
  '';

  # Propagate home.sessionPath into fish. Home-manager only writes sessionPath
  # into hm-session-vars.sh (bash/zsh); fish needs this shim because
  # programs.fish.enable is not set at the home-manager level here.
  home.file.".config/fish/conf.d/01-session-path.fish".text = ''
    fish_add_path -gp ${lib.concatStringsSep " " config.home.sessionPath}
  '';

  # Note: All other Fish configuration (config.fish, functions, other conf.d files)
  # remains in chezmoi at ~/.config/fish/
  # This allows applications to auto-configure Fish while keeping direnv working
}
