function ghostty-here -d "Open new Ghostty window in a directory (default: current)"
    set -l dir (test (count $argv) -gt 0; and realpath $argv[1]; or pwd)
    # Unset ZELLIJ so the new Ghostty window's shell starts a fresh Zellij session
    # Pass dir via env var — --working-directory is unreliable via open -na in Ghostty 1.2
    env -u ZELLIJ -u ZELLIJ_SESSION_NAME -u USE_TMUX -u SKIP_MUX -u TMUX -u TMUX_SESSION_NAME -u TMUX_LAYOUT_SCRIPT -u CLAUDE_WORKTREE GHOSTTY_TARGET_DIR=$dir open -na Ghostty.app --args --working-directory=$dir --quit-after-last-window-closed
end
