{ config, pkgs, lib, ... }:

let
  home = config.home.homeDirectory;

  # Directories to scan for project configs
  # Each contains <namespace>/<project>/.envrc
  projectSources = [
    "${home}/.config/nix/projects"          # Public projects (via chezmoi symlink)
    "${home}/.config/private/nix/projects"  # Private projects (via chezmoi external)
  ];
in {
  home.activation.linkProjects = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    echo "[link-projects] Setting up .envrc symlinks for projects..."

    link_envrc() {
      local src="$1"
      local dest="$2"

      if [ -f "$src" ]; then
        mkdir -p "$(dirname "$dest")"
        ln -sf "$src" "$dest"
        echo "  Linked: $dest -> $src"
      fi
    }

    for source_dir in ${lib.concatStringsSep " " (map (s: ''"${s}"'') projectSources)}; do
      [ -d "$source_dir" ] || continue

      # Iterate over <namespace>/<project>/.envrc
      for namespace_dir in "$source_dir"/*/; do
        [ -d "$namespace_dir" ] || continue
        namespace="$(basename "$namespace_dir")"

        for project_dir in "$namespace_dir"*/; do
          [ -d "$project_dir" ] || continue
          project="$(basename "$project_dir")"

          if [ -f "$project_dir/.envrc" ]; then
            link_envrc \
              "$project_dir/.envrc" \
              "${home}/Code/$namespace/$project/.envrc"
          fi
        done
      done
    done

    echo "[link-projects] Done!"
  '';
}
