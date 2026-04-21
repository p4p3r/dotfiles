#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Ghostty (Vanilla)
# @raycast.mode silent
# @raycast.packageName Dev Tools

# Optional parameters:
# @raycast.icon 👻
# @raycast.description Open Ghostty without Zellij or tmux

# cd $HOME so `ghostty-bare` (which defaults to `pwd`) opens the window
# in the user's home rather than this script's directory.
cd "$HOME"
/run/current-system/sw/bin/fish -c 'ghostty-bare'

# Bring Ghostty to front
osascript -e 'tell application "Ghostty" to activate'
