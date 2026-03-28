function claude-worktree -d "Open new Ghostty window with Claude Code worktree session"
    if test (count $argv) -eq 0
        echo "Usage: claude-worktree <worktree-name>"
        return 1
    end

    if not git rev-parse --is-inside-work-tree &>/dev/null
        echo "Error: not in a git repository"
        return 1
    end

    set -l name $argv[1]
    set -l repo_root (git rev-parse --show-toplevel)
    set -l repo_name (basename $repo_root)
    set -l session_name "$repo_name~$name"
    set -l fish_bin (command -s fish)

    # Launcher script sets env vars and execs into interactive login fish.
    # Needed because env vars don't survive `open -na` on macOS.
    set -l launcher (mktemp /tmp/cwt-XXXXXX)
    printf '%s\n' \
        "#!$fish_bin" \
        "rm (status filename)" \
        "set -gx ZELLIJ_SESSION_NAME $session_name" \
        "set -gx CLAUDE_WORKTREE $name" \
        "exec $fish_bin -il" \
        >$launcher
    chmod +x $launcher

    open -na Ghostty.app --args \
        --working-directory=$repo_root \
        --quit-after-last-window-closed \
        --command=$launcher
end
