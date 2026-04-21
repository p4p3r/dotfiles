function ad-orphans -d "List agent-deck worktrees whose tmux session is gone; optionally re-spawn one"
    set -l wt_root $HOME/.agent-deck/multi-repo-worktrees
    if not test -d $wt_root
        echo "ad-orphans: $wt_root does not exist" >&2
        return 1
    end

    # --reattach <path>: hand off to `ad`, which creates a fresh agent-deck session
    # bound to the worktree (and spawns a new tmux session server-side).
    if test (count $argv) -ge 1; and test "$argv[1]" = --reattach
        if test (count $argv) -lt 2
            echo "ad-orphans --reattach <worktree-path>" >&2
            return 1
        end
        set -l target (realpath $argv[2])
        if not test -d $target
            echo "ad-orphans: $target is not a directory" >&2
            return 1
        end
        ad $target
        return
    end

    # Gather current tmux pane paths (each pane's cwd). A worktree is considered
    # alive if any live pane is rooted inside it.
    set -l live_paths
    if tmux has-session 2>/dev/null
        set live_paths (tmux list-panes -a -F '#{pane_current_path}' 2>/dev/null)
    end

    set -l any_orphan 0
    for wt in $wt_root/*/
        set -l wt_path (string trim --right --chars=/ $wt)
        set -l name (basename $wt_path)
        set -l alive 0
        for p in $live_paths
            if string match -q "$wt_path*" $p
                set alive 1
                break
            end
        end
        if test $alive -eq 0
            set any_orphan 1
            echo "orphan  $wt_path"
        else
            echo "alive   $wt_path"
        end
    end

    if test $any_orphan -eq 1
        echo
        echo "Reattach one with:  ad-orphans --reattach <path>"
        echo "(this spawns a fresh agent-deck window; worktree git state and Claude history are preserved.)"
    end
end
