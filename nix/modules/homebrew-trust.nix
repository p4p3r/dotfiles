{ pkgs, lib, ... }:

# Homebrew 6 refuses to load formulae and casks from third-party taps until
# they are explicitly trusted, and warns it cannot check the rest for updates.
# Before this, `nix_switch` failed outright: brew bundle aborted on the first
# untrusted cask and darwin-rebuild exited 1.
#
# The file must be a REAL file, not a home.file store symlink. brew resolves
# ~/.homebrew/trust.json and then checks the ownership of the *resolved* file's
# parent directory; pointed at /nix/store that is root-owned, and brew bails
# with "Refusing to write insecure trust store", which breaks `brew install`
# entirely. So it is installed by an activation script instead.
#
# Consequence: brew's own `brew trust` writes (e.g. the "trustedformulae" key
# it adds when you install from a tap explicitly) are overwritten on the next
# switch. That is fine — trusting the tap already covers its formulae — but it
# does mean this list is the single source of truth.
#
# Least privilege: only taps that actually need trust are listed. Trusting a
# tap trusts everything it ships now AND in future, so add one only after
# checking who publishes it. Every tap here was verified to resolve to a repo
# owned by its declared owner.

let
  jsonFormat = pkgs.formats.json { };

  trustedTaps = [
    "asheshgoplani/tap"     # agent-deck
    "cirruslabs/cli"        # tart, softnet
    "felixkratz/formulae"   # sketchybar
    "mutagen-io/mutagen"    # mutagen
    "nikitabobko/tap"       # aerospace
    "osx-cross/arm"         # arm-gcc-bin@10 (QMK toolchain)
    "osx-cross/avr"         # avr-gcc@8, pulled in as a qmk dependency
    "qmk/qmk"               # qmk, hid_bootloader_cli, mdloader
  ];

  trustFile = jsonFormat.generate "homebrew-trust.json" {
    trustedtaps = lib.sort (a: b: a < b) trustedTaps;
  };
in
lib.mkIf pkgs.stdenv.isDarwin {
  home.activation.homebrewTrustStore =
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      run install -d -m 700 "$HOME/.homebrew"
      run install -m 600 ${trustFile} "$HOME/.homebrew/trust.json"
    '';
}
