{ pkgs, lib, ... }:

# Homebrew 6 refuses to load formulae and casks from third-party taps until
# they are explicitly trusted, and warns it cannot check the rest for updates.
# Before this, `nix_switch` failed outright: brew bundle aborted on the first
# untrusted cask (aerospace) and darwin-rebuild exited 1.
#
# `brew trust` records the decision in ~/.homebrew/trust.json — not under
# ~/.config, because XDG_CONFIG_HOME is unset on this machine. Declaring the
# file here keeps trust in version control instead of imperative local state
# that no other machine would inherit.
#
# Least privilege: only taps that actually need it are listed. datadog-labs/pack
# stays out — it is tapped but has nothing installed, so nothing ever loads it.
# Trusting a tap trusts everything it ships now AND in future, so add one only
# after checking who publishes it. Every tap here was verified to resolve to a
# repo owned by its declared owner, except koekeishiya (see below).
#
# Note this makes the file a read-only store symlink, so `brew trust` can no
# longer write it. Adding a tap is a nix edit + switch, which is the point.

let
  jsonFormat = pkgs.formats.json { };

  trustedTaps = [
    "asheshgoplani/tap"     # agent-deck
    "cirruslabs/cli"        # tart
    # sketchybar and graphite are installed from these but not declared in
    # homebrew.brews. cleanup = "zap" still has to LOAD every installed formula
    # to decide what to remove, and loading an untrusted one is a hard error —
    # so these need trusting even though nothing declares them.
    "felixkratz/formulae"   # sketchybar
    "withgraphite/tap"      # graphite
    # skhd/yabai. Listed by clone URL, not "koekeishiya/formulae": the tap is
    # pinned to an explicit clone_target in darwin-homebrew.nix, and brew keys
    # trust for such taps by URL. That is the safer shape anyway — a URL cannot
    # be taken over by whoever now holds the freed "koekeishiya" username.
    "https://github.com/asmvik/homebrew-formulae.git"
    "mutagen-io/mutagen"    # mutagen
    "nikitabobko/tap"       # aerospace
    "osx-cross/arm"         # arm-gcc-bin@10 (QMK toolchain)
    "osx-cross/avr"         # avr-gcc@8, pulled in as a qmk dependency
    "qmk/qmk"               # qmk, hid_bootloader_cli
  ];
in
lib.mkIf pkgs.stdenv.isDarwin {
  home.file.".homebrew/trust.json".source =
    jsonFormat.generate "homebrew-trust.json" {
      trustedtaps = lib.sort (a: b: a < b) trustedTaps;
    };
}
