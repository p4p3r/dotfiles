{ config, pkgs, lib, ... }:

let
  profilesEnv = lib.getEnv "PROFILES";
  profiles =
    if profilesEnv == "" then [ "personal" ] else
    map (p: lib.trim p) (lib.splitString "," profilesEnv);

  home = config.home.homeDirectory;
  # Private repo is cloned by chezmoi (.chezmoiexternal.toml) to ~/.config/private/
  repoRoot = "${home}/.config/private";
  overlayRoot = "${repoRoot}/overlay";
  scriptsRoot = "${repoRoot}/scripts";

  run = pkgs.writeShellScript "private-restore.sh" ''
    set -euo pipefail

    if [ ! -d "${repoRoot}" ]; then
      echo "[private-restore] Private repo not found at ${repoRoot}"
      echo "[private-restore] Run 'chezmoi apply' first to clone it via .chezmoiexternal.toml"
      exit 1
    fi

    # Overlays: common then per-profile
    sync_one() {
      local src="$1"
      [ -d "$src" ] || return 0
      ${pkgs.findutils}/bin/find "$src" -mindepth 1 -maxdepth 1 -type d | while read -r sub; do
        rel="''${sub#${overlayRoot}/}"
        dest="$HOME$rel"
        mkdir -p "$dest"
        if [ -x "${pkgs.rsync}/bin/rsync" ]; then
          ${pkgs.rsync}/bin/rsync -a "$sub/" "$dest/"
        else
          cp -R "$sub/." "$dest/"
        fi
      done
    }

    [ -d "${overlayRoot}/common" ] && sync_one "${overlayRoot}/common"
    IFS=, read -r -a profs <<< "''${profilesEnv:-personal}"
    for p in "''${profs[@]}"; do
      p_trim="$(echo "$p" | ${pkgs.gnused}/bin/sed 's/^ *//; s/ *$//')"
      [ -z "$p_trim" ] && continue
      sync_one "${overlayRoot}/$p_trim"
    done

    # Private packages per profile
    install_pkgs_macos() {
      local p="$1"
      local pkgdir="${overlayRoot}/private-packages/$p/macos/pkg"
      [ -d "$pkgdir" ] || return 0
      for f in "$pkgdir"/*.pkg; do
        [ -e "$f" ] || continue
        sudo installer -pkg "$f" -target /
      done
      local tdir="${overlayRoot}/private-packages/$p/macos/tarballs"
      [ -d "$tdir" ] && { mkdir -p "$HOME/tmp"; cp -f "$tdir"/*.* "$HOME/tmp" || true; }
    }
    install_pkgs_linux() {
      local p="$1"
      local dpkgdir="${overlayRoot}/private-packages/$p/linux/dpkg"
      if [ -d "$dpkgdir" ]; then
        for f in "$dpkgdir"/*.deb; do
          [ -e "$f" ] || continue
          sudo dpkg -i "$f" || sudo apt-get -f install -y
        done
      fi
      local tdir="${overlayRoot}/private-packages/$p/linux/tarballs"
      [ -d "$tdir" ] && { mkdir -p "$HOME/tmp"; cp -f "$tdir"/*.* "$HOME/tmp" || true; }
    }
    uname_s="$(${pkgs.coreutils}/bin/uname -s)"
    for p in "''${profs[@]}"; do
      case "$uname_s" in
        Darwin) install_pkgs_macos "$p";;
        Linux)  install_pkgs_linux "$p";;
      esac
    done

    # Per-profile bootstrap scripts
    for p in "''${profs[@]}"; do
      scr="${scriptsRoot}/bootstrap_$p.sh"
      if [ -x "$scr" ]; then
        echo "[private-restore] Running $scr"
        "$scr"
      fi
    done
  '';
in {
  home.activation.privateRestore = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [[ "''${PRIVATE_RESTORE:-}" == "yes" ]]; then
      PROFILES="''''${profilesEnv:-personal}" ${run}
    else
      echo "[private-restore] Skipping (set PRIVATE_RESTORE=yes to run)"
    fi
  '';
}
