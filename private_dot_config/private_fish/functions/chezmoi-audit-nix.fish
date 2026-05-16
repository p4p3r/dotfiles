function chezmoi-audit-nix --description "Flag chezmoi-tracked files that resolve to /nix/store/ symlinks (home-manager owns them — should be in .chezmoiignore)"
    # Why this matters: a chezmoi `symlink_*` source whose body is a
    # /nix/store/<hash>/... path binds chezmoi to ONE specific HM generation.
    # The hash rotates every `nix_switch`, so the next `chezmoi apply` sees
    # the live target ≠ source-recorded target and prompts:
    #   "has changed since chezmoi last wrote it? diff/overwrite/all-…/skip/quit"
    #
    # Cleanup recipe per flagged file:
    #   1. `rm` the chezmoi source (find via `chezmoi source-path <live-path>`)
    #   2. Add the destination path to `.chezmoiignore`
    #   3. Let home-manager keep owning it
    set -l misconfigured 0
    for f in (chezmoi managed)
        set -l live $HOME/$f
        if test -L $live
            if string match -q '/nix/store/*' (readlink $live)
                echo "MISCONFIG: $f → "(readlink $live)
                set misconfigured (math $misconfigured + 1)
            end
        end
    end
    if test $misconfigured -eq 0
        echo "OK — no chezmoi-tracked files resolve to /nix/store/ symlinks."
        return 0
    end
    echo
    echo "$misconfigured file(s) flagged. For each:"
    echo "  1. chezmoi source-path <live-path>   # find the chezmoi source"
    echo "  2. rm <source-path>                  # delete the stale symlink_*"
    echo "  3. Add the destination path to ~/.config/chezmoi/.chezmoiignore"
    echo "  4. Commit + push the dotfiles repo"
    return 1
end
