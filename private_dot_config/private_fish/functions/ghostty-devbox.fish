function ghostty-devbox -d "Open a bare Ghostty window that ssh's straight into the devbox tmux session"
    # The whole point: keep the multiplexer count at exactly 1 — the tmux
    # session running on the devbox. Bare Ghostty (no laptop zellij/tmux),
    # then `sg-devbox tmux` attaches the persistent agent session.
    #
    # If the remote shell still tries to start zellij despite this (e.g. you
    # SSH'd via a different path), conf.d/30-zellij.fish also skips when
    # SSH_CONNECTION/SSH_TTY is set.
    #
    # Wrapper logic:
    #  - If sg-devbox tmux SUCCEEDS, the exec'd ssh holds the window for the
    #    lifetime of the tmux session. Detach with Ctrl-B D → window closes.
    #  - If it FAILS (e.g. Tailscale DNS not yet resolving right after an
    #    auto-start), retry a few times with backoff. If still failing, drop
    #    to an interactive fish so you can read the error and reconnect by
    #    typing `sg-devbox tmux` again instead of staring at an instantly
    #    closing window.
    set -l wrap '
        for i in 1 2 3 4 5
            sg-devbox tmux
            and exit 0
            echo
            echo "sg-devbox tmux attempt $i failed. Retrying in 10s…"
            sleep 10
        end
        echo
        echo "sg-devbox tmux failed 5x. Dropping to a shell so you can investigate."
        exec fish -l
    '
    env -u ZELLIJ -u ZELLIJ_SESSION_NAME -u USE_TMUX SKIP_MUX=1 \
        open -na Ghostty.app --args \
            --command="fish -lic '$wrap'" \
            --quit-after-last-window-closed
end
