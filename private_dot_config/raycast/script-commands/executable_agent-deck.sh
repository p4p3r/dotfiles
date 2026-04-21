#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Agent Deck
# @raycast.mode silent
# @raycast.packageName Dev Tools

# Optional parameters:
# @raycast.icon 🎛
# @raycast.description Open agent-deck TUI in a new Ghostty window

# cd $HOME so `ad` (which defaults to `pwd` when no path is given) opens
# the window in the user's home rather than this script's directory.
cd "$HOME"
/run/current-system/sw/bin/fish -c 'ad'

# Bring Ghostty to front
osascript -e 'tell application "Ghostty" to activate'
