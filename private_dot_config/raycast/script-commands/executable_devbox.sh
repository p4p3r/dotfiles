#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Devbox
# @raycast.mode silent
# @raycast.packageName Dev Tools

# Optional parameters:
# @raycast.icon 📦
# @raycast.description Open a bare Ghostty + attach to a remote tmux session on the devbox (default 'main')
# @raycast.argument1 { "type": "text", "placeholder": "session", "optional": true }

# Bare Ghostty (no local zellij/tmux) → sg-devbox tmux on the remote.
# Single multiplexer in the chain = the remote tmux. Use for ad-hoc shells
# and long-running commands that should survive disconnect.
SESSION="${1:-}"
cd "$HOME"
/run/current-system/sw/bin/fish -c "ghostty-devbox tmux $SESSION"

# Bring Ghostty to front
osascript -e 'tell application "Ghostty" to activate'
