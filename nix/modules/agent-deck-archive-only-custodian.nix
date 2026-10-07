{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-archive-only-custodian;
in
{
  options.programs.agent-deck-archive-only-custodian.enable = lib.mkEnableOption "the manual archive-only custodian companion";

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "programs.agent-deck-archive-only-custodian is supported only on Linux.";
      }
    ];
    home.packages = [ (import ../lib/agent-deck-archive-only-custodian.nix { inherit pkgs; }) ];
  };
}
