#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Devbox Deck
# @raycast.mode silent
# @raycast.packageName Dev Tools

# Optional parameters:
# @raycast.icon 🎴
# @raycast.description Open a bare Ghostty + run agent-deck directly on the devbox (no outer tmux)

# Bare Ghostty (no local zellij/tmux) → sg-devbox ad on the remote.
# agent-deck manages its own internal tmux for per-agent persistence —
# closing the window leaves agents running. Re-run this command to reopen.
cd "$HOME"
/run/current-system/sw/bin/fish -c 'ghostty-devbox ad'

# Bring Ghostty to front
osascript -e 'tell application "Ghostty" to activate'
