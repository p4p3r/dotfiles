#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Devbox
# @raycast.mode silent
# @raycast.packageName Dev Tools

# Optional parameters:
# @raycast.icon 📦
# @raycast.description Open a bare Ghostty that ssh's straight into the devbox tmux session

# Bare Ghostty (no local zellij/tmux) → sg-devbox tmux on the remote.
# Single multiplexer in the chain = the remote tmux that agent-deck plugs into.
cd "$HOME"
/run/current-system/sw/bin/fish -c 'ghostty-devbox'

# Bring Ghostty to front
osascript -e 'tell application "Ghostty" to activate'
