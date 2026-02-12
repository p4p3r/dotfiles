{ pkgs, lib, ... }:
{
  # Nix performance and maintenance settings
  nix = {
    # Performance optimization
    settings = {
      # Use all available CPU cores for builds
      max-jobs = "auto";
      cores = 0;  # 0 means use all available cores per job

      # Keep build outputs and derivations for better caching
      keep-outputs = true;
      keep-derivations = true;

      # Better error messages with full stack traces
      show-trace = true;

      # Trusted users for binary cache operations
      trusted-users = [ "root" "@admin" ];

      # Binary caches for faster builds
      substituters = [
        "https://cache.nixos.org"
        "https://nix-community.cachix.org"
        "https://devenv.cachix.org"
      ];

      trusted-public-keys = [
        "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
        "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
        "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
      ];

      # Experimental features (already enabled in flake.nix but good to be explicit)
      experimental-features = [ "nix-command" "flakes" ];
    };

    # Automatic garbage collection
    gc = {
      automatic = true;
      interval = { Day = 7; };  # Run weekly on Sundays
      options = "--delete-older-than 30d";
    };

    # Optimize store automatically during GC
    optimise = {
      automatic = true;
    };
  };
}
