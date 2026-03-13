# Auto-run command based on marker file in cwd (used by claude-worktree)
if status is-interactive; and test -f .claude-autorun
    rm .claude-autorun
    cclaude
end
