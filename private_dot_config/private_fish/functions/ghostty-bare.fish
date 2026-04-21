function ghostty-bare -d "Open Ghostty without Zellij or tmux (for agent-deck, etc.)"
    set -l dir (test (count $argv) -gt 0; and realpath $argv[1]; or pwd)
    # SKIP_MUX prevents both 30-zellij.fish and 30-tmux.fish from launching
    env -u ZELLIJ -u ZELLIJ_SESSION_NAME -u USE_TMUX SKIP_MUX=1 GHOSTTY_TARGET_DIR=$dir \
        open -na Ghostty.app --args --working-directory=$dir --quit-after-last-window-closed
end
