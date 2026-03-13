function ghostty-here -d "Open new Ghostty window in a directory (default: current)"
    set -l dir (test (count $argv) -gt 0; and realpath $argv[1]; or pwd)
    # Unset ZELLIJ so the new Ghostty window's shell starts a fresh Zellij session
    env -u ZELLIJ -u ZELLIJ_SESSION_NAME open -na Ghostty.app --args --working-directory=$dir
end
