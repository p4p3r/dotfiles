#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Agent Deck Here
# @raycast.mode silent
# @raycast.packageName Dev Tools

# Optional parameters:
# @raycast.icon 🎛
# @raycast.argument1 { "type": "text", "placeholder": "project name or path", "optional": false }
# @raycast.argument2 { "type": "text", "placeholder": "worktree branch (optional)", "optional": true }
# @raycast.description Create a Claude session in a project directory via agent-deck

input="$1"
worktree="$2"

# Resolve project directory
resolved=""
for base in ~/Code/semgrep ~/Code/p4p3r ~/Code/other; do
  match="$base/$input"
  if [ -d "$match" ]; then
    resolved="$match"
    break
  fi
done

# Fallback: try as a direct path (expand ~)
if [ -z "$resolved" ]; then
  expanded="${input/#\~/$HOME}"
  if [ -d "$expanded" ]; then
    resolved="$expanded"
  fi
fi

if [ -z "$resolved" ]; then
  echo "Directory not found: $input"
  exit 1
fi

if [ -n "$worktree" ]; then
  /run/current-system/sw/bin/fish -c "ad $resolved --worktree $worktree --new-branch"
else
  /run/current-system/sw/bin/fish -c "ad $resolved"
fi

# Bring Ghostty to front
osascript -e 'tell application "Ghostty" to activate'
