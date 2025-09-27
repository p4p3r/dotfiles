{ config, pkgs, lib, ... }:

let
  profilesEnv = lib.getEnv "PROFILES";
  profiles =
    if profilesEnv == "" then [ "personal" ] else
    map (p: lib.trim p) (lib.splitString "," profilesEnv);

  home = config.home.homeDirectory;
  repoCache = "${home}/.cache/private-bootstrap";
  repoRoot  = "${repoCache}/repo";
  overlayRoot = "${repoRoot}/overlay";
  manifestsRoot = "${overlayRoot}/manifests";
  scriptsRoot = "${repoRoot}/scripts";

  privateRepo = "git@github.com:p4p3r/dotfiles-private.git";
  opTokenRef = "op://<Vault>/<Item>/<Field>";

  run = pkgs.writeShellScript "private-restore.sh" ''
    set -euo pipefail

    mkdir -p "${repoCache}"

    clone_https_with_token() {
      local https_url token
      https_url=$(echo "${privateRepo}" | sed -E 's#git@github.com:(.+)#https://github.com/\1#')
      token=$(op read "${opTokenRef}")
      GIT_ASKPASS=/bin/true \
      git -c http.extraHeader="AUTHORIZATION: basic $(printf "x:%s" "$token" | base64)" \
        clone --depth=1 "$https_url" "${repoRoot}"
    }

    if [ ! -d "${repoRoot}/.git" ]; then
      if ! git clone --depth=1 "${privateRepo}" "${repoRoot}"; then
        echo "[private-restore] SSH clone failed, trying HTTPS via op token…" >&2
        clone_https_with_token
      fi
    else
      git -C "${repoRoot}" fetch --prune
      git -C "${repoRoot}" pull --ff-only
    fi

    # Overlays: common then per-profile
    sync_one() {
      local src="$1"
      [ -d "$src" ] || return 0
      find "$src" -mindepth 1 -maxdepth 1 -type d | while read -r sub; do
        rel="''${sub#${overlayRoot}/}"
        dest="$HOME$rel"
        mkdir -p "$dest"
        if command -v rsync >/dev/null 2>&1; then
          rsync -a "$sub/" "$dest/"
        else
          cp -R "$sub/." "$dest/"
        fi
      done
    }

    [ -d "${overlayRoot}/common" ] && sync_one "${overlayRoot}/common"
    IFS=, read -r -a profs <<< "''${profilesEnv:-personal}"
    for p in "''${profs[@]}"; do
      p_trim="$(echo "$p" | sed 's/^ *//; s/ *$//')"
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
    uname_s="$(uname -s)"
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
    PROFILES="''''${profilesEnv:-personal}" ${run}
  '';
}
