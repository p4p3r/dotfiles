function ad -d "Open agent-deck in a new bare Ghostty window"
    set -l dir ""
    set -l extra_args

    # Parse args: first non-flag arg is the directory, rest passed to agent-deck
    for arg in $argv
        if test -z "$dir"; and not string match -q -- '--*' $arg
            set dir (realpath $arg)
        else
            set -a extra_args $arg
        end
    end

    set -l fish_bin (command -s fish)
    set -l launcher (mktemp /tmp/ad-XXXXXX)

    if test -z "$dir"
        # No dir: just open agent-deck TUI
        printf '%s\n' \
            "#!$fish_bin" \
            "rm (status filename)" \
            "set -gx SKIP_MUX 1" \
            "exec $fish_bin -ilc agent-deck" \
            >$launcher
    else
        # Dir provided: create a claude session (with optional extra args like --worktree)
        set -l ad_cmd "agent-deck add $dir -c claude $extra_args; exec agent-deck"
        printf '%s\n' \
            "#!$fish_bin" \
            "rm (status filename)" \
            "set -gx SKIP_MUX 1" \
            "set -gx GHOSTTY_TARGET_DIR $dir" \
            "exec $fish_bin -ilc '$ad_cmd'" \
            >$launcher
    end

    chmod +x $launcher
    set -l wd (test -n "$dir"; and echo $dir; or pwd)
    # Use --initial-command (not --command): --command sets the instance-wide
    # default, so every new window in the same Ghostty instance would re-exec
    # this temp launcher — which self-deletes, producing "No such file or
    # directory" on subsequent cmd+N. --initial-command applies to the first
    # window only; new windows fall back to the default shell.
    open -na Ghostty.app --args --working-directory=$wd --quit-after-last-window-closed --initial-command=$launcher
end
