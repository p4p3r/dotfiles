#!/usr/bin/env bash
set -euo pipefail

# Ghostty sets TERM=xterm-ghostty, but most terminfo databases (including
# the one ncurses ships) only define "ghostty" without that alias, causing
# "missing or unsuitable terminal: xterm-ghostty" in ncurses-based TUIs
# (e.g. agent-deck) on remote/non-Ghostty hosts.
if ! infocmp xterm-ghostty >/dev/null 2>&1; then
  tic -x -o "$HOME/.terminfo" - <<'EOF'
xterm-ghostty|Ghostty terminal emulator (xterm-ghostty alias),
	use=ghostty,
EOF
fi
