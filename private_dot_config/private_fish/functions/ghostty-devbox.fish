function ghostty-devbox -d "Open a bare Ghostty window that ssh's straight into the devbox" -a mode session_name
    # Open a bare Ghostty window (no laptop zellij/tmux) and ssh straight into
    # the devbox. Two modes:
    #
    #   ghostty-devbox ad              → run agent-deck directly (no outer tmux).
    #                                    agent-deck manages its own internal tmux
    #                                    for per-agent persistence.
    #   ghostty-devbox tmux            → attach/create tmux session 'main'
    #   ghostty-devbox tmux <name>     → attach/create tmux session <name>
    #
    # Default mode (no args) = ad. Matches the "Devbox Deck" Raycast command;
    # `ghostty-devbox tmux …` backs the "Devbox" Raycast command.
    #
    # Wrapper logic:
    #  - If the sg-devbox call SUCCEEDS, the exec'd ssh holds the window for
    #    the lifetime of the remote session.
    #  - If it FAILS (e.g. Tailscale DNS not yet resolving right after auto-
    #    start), retry a few times with backoff. If still failing, drop to an
    #    interactive fish so you can read the error and reconnect manually.
    #  - 30-zellij.fish ALSO skips zellij when SSH_CONNECTION/SSH_TTY is set,
    #    so even if you SSH'd via a different path the multiplexer count stays
    #    at 1 (the remote tmux or agent-deck's internal tmux).
    test -z "$mode"; and set mode ad

    set -l cmd
    switch $mode
        case ad agent-deck
            set cmd "sg-devbox ad"
        case tmux
            if test -n "$session_name"
                set cmd "sg-devbox tmux $session_name"
            else
                set cmd "sg-devbox tmux"
            end
        case '*'
            echo "Unknown mode: $mode (expected: ad | tmux)" >&2
            return 1
    end

    set -l wrap "
        for i in 1 2 3 4 5
            $cmd
            and exit 0
            echo
            echo \"$cmd attempt \$i failed. Retrying in 10s…\"
            sleep 10
        end
        echo
        echo \"$cmd failed 5x. Dropping to a shell so you can investigate.\"
        exec fish -l
    "

    env -u ZELLIJ -u ZELLIJ_SESSION_NAME -u USE_TMUX SKIP_MUX=1 \
        open -na Ghostty.app --args \
            --command="fish -lic '$wrap'" \
            --quit-after-last-window-closed
end
