function ghostty-devbox -d "Open a bare Ghostty window that ssh's straight into the devbox tmux session"
    # The whole point: keep the multiplexer count at exactly 1 — the tmux
    # session running on the devbox. Bare Ghostty (no laptop zellij/tmux),
    # then `sg-devbox tmux` attaches the persistent agent session.
    #
    # If the remote shell still tries to start zellij despite this (e.g. you
    # SSH'd via a different path), conf.d/30-zellij.fish also skips when
    # SSH_CONNECTION/SSH_TTY is set.
    env -u ZELLIJ -u ZELLIJ_SESSION_NAME -u USE_TMUX SKIP_MUX=1 \
        open -na Ghostty.app --args \
            --command="fish -ic 'sg-devbox tmux'" \
            --quit-after-last-window-closed
end
