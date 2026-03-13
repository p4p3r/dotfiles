function fish_get_session_name -d "Get zellij session name based on current directory"
    if git rev-parse --is-inside-work-tree &>/dev/null
        set -l repo_root (git rev-parse --show-toplevel)
        set -l repo_name (basename $repo_root)

        # Detect worktree: .git is a file (not dir) in worktrees
        if test -f $repo_root/.git
            # Get original repo name from the git-common-dir path
            set -l common_dir (git rev-parse --git-common-dir)
            set -l main_repo (basename (string replace -- '/worktrees' '' (dirname $common_dir)))
            set -l branch (git branch --show-current 2>/dev/null; or echo wt)
            set branch (string replace -a '/' '-' $branch)
            echo (_shorten_name $main_repo)"~"$branch
        else
            echo $repo_name
        end
    else if string match -q "$HOME/.config*" (pwd)
        echo config
    else if test (pwd) = $HOME; or string match -q "$HOME/Code" (pwd); or string match -q "$HOME/Projects" (pwd)
        echo main
    else
        echo (basename (pwd))
    end
end
