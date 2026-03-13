function claude-worktree -d "Create git worktree and open in new Ghostty window"
    if test (count $argv) -eq 0
        echo "Usage: claude-worktree <branch-name> [base-branch]"
        echo "Example: claude-worktree claudio/harness develop"
        return 1
    end

    if not git rev-parse --is-inside-work-tree &>/dev/null
        echo "Error: not in a git repository"
        return 1
    end

    set -l branch_name $argv[1]
    set -l base_branch main
    if test (count $argv) -ge 2
        set base_branch $argv[2]
    end

    set -l repo_name (basename (git rev-parse --show-toplevel))
    set -l safe_branch (string replace -a '/' '-' $branch_name)
    set -l worktree_path (git rev-parse --show-toplevel)/../$repo_name-$safe_branch

    if not test -d $worktree_path
        # Use existing branch if it exists, otherwise create new one
        if git rev-parse --verify $branch_name &>/dev/null
            git worktree add $worktree_path $branch_name
        else
            git worktree add $worktree_path -b $branch_name $base_branch
        end
        or return 1
        echo "Worktree created at $worktree_path"

        set -l repo_root (git rev-parse --show-toplevel)
        if test -f $repo_root/.envrc
            ln -s $repo_root/.envrc $worktree_path/.envrc
            direnv allow $worktree_path
        end
    end

    touch $worktree_path/.claude-autorun
    ghostty-here $worktree_path
end
