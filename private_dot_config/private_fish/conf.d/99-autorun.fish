# Auto-launch Claude worktree session (set by claude-worktree)
if status is-interactive; and set -q CLAUDE_WORKTREE
    set -l _wt $CLAUDE_WORKTREE
    set -e CLAUDE_WORKTREE
    claude -w $_wt
end
