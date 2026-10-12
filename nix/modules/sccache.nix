{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.sccache-shared;
in
{
  options.programs.sccache-shared = {
    enable = lib.mkEnableOption "a machine-wide shared Rust compilation cache";

    cacheDirectory = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.cache/sccache";
      description = "Directory holding the shared cache.";
    };

    maxSize = lib.mkOption {
      type = lib.types.str;
      default = "50G";
      description = ''
        Upper bound on the cache. sccache evicts least-recently-used entries at
        this bound, so the cache cannot become the next disk problem.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ pkgs.sccache ];

    # Shared compilation cache rather than a shared CARGO_TARGET_DIR. A single
    # target directory would be the obvious way to stop N worktrees each
    # carrying their own build output, but cargo takes an exclusive lock on a
    # target directory for the length of a build: concurrent builds would queue
    # behind each other instead of sharing anything. sccache is keyed per
    # compilation unit and needs no such lock, so parallel builds in different
    # worktrees both hit the cache and neither blocks.
    home.sessionVariables = {
      RUSTC_WRAPPER = "${pkgs.sccache}/bin/sccache";
      SCCACHE_DIR = cfg.cacheDirectory;
      SCCACHE_CACHE_SIZE = cfg.maxSize;
    };

    # The fish module shims only its own shared variables and does not import
    # hm-session-vars.sh, so a fresh login would otherwise miss these.
    home.file.".config/fish/conf.d/87-sccache.fish".text = ''
      set -gx RUSTC_WRAPPER ${lib.escapeShellArg "${pkgs.sccache}/bin/sccache"}
      set -gx SCCACHE_DIR ${lib.escapeShellArg cfg.cacheDirectory}
      set -gx SCCACHE_CACHE_SIZE ${lib.escapeShellArg cfg.maxSize}
    '';
  };
}
