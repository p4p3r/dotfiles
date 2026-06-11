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

# Base directories to scan for the project name. Kept configurable so machine-
# or work-specific roots can be added without baking them into this public
# script. Resolution order:
#   - AGENT_DECK_BASE_DIRS env var (whitespace-separated) overrides everything
#   - ~/.config/agent-deck/base-dirs file (whitespace-separated; may be
#     deployed by a private overlay)
#   - personal default
cfg="$HOME/.config/agent-deck/base-dirs"
if [ -n "$AGENT_DECK_BASE_DIRS" ]; then
  base_dirs="$AGENT_DECK_BASE_DIRS"
elif [ -f "$cfg" ]; then
  base_dirs="$(cat "$cfg")"
else
  base_dirs="$HOME/Code/p4p3r $HOME/Code/other"
fi

# Resolve project directory
resolved=""
for base in $base_dirs; do
  base="${base/#\~/$HOME}"
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
