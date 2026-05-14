#!/usr/bin/env bash
set -euo pipefail

LOG="/tmp/aerospace-collapse-debug.log"
TMP="/tmp/aerospace-collapse-windows.txt"

{
  echo "==== collapse-to-1.sh: $(date) ===="
  echo "PATH=$PATH"

  AEROSPACE_BIN="${AEROSPACE_BIN:-$(command -v aerospace || true)}"
  echo "AEROSPACE_BIN='$AEROSPACE_BIN'"

  if [[ -z "${AEROSPACE_BIN}" ]]; then
    echo "ERROR: aerospace binary not found in PATH"
    exit 1
  fi

  # Dump and inspect raw list
  "$AEROSPACE_BIN" list-windows --all --format $'%{window-id}%{tab}%{app-bundle-id}%{tab}%{workspace}%{tab}%{monitor-name}%{newline}' > "$TMP" || true
  echo "Raw output (first 200 lines):"
  sed -n '1,200p' "$TMP" || true
  echo "Total lines: $(wc -l < "$TMP" 2>/dev/null || true)"
  echo

  echo "Processing lines..."
  while IFS=$'\t' read -r win_id bundle ws mon; do
    # skip empty lines
    [[ -z "${win_id//[[:space:]]/}" ]] && continue

    echo "  line -> win_id='${win_id}' bundle='${bundle:-}' ws='${ws:-}' mon='${mon:-}'"

    # Redirect stdin from /dev/null for safety; ensures aerospace can't consume our loop input
    if "$AEROSPACE_BIN" move-node-to-workspace --window-id "$win_id" 1 </dev/null; then
      echo "    moved $win_id -> 1"
    else
      echo "    move FAILED for $win_id"
    fi
  done < "$TMP"

  echo
  echo "Flatten & balance workspace 1, then focus it..."
  "$AEROSPACE_BIN" flatten-workspace-tree --workspace 1 </dev/null || echo "  flatten failed"
  "$AEROSPACE_BIN" balance-sizes --workspace 1 </dev/null || echo "  balance failed"
  "$AEROSPACE_BIN" workspace 1 </dev/null || echo "  workspace focus failed"
  "$AEROSPACE_BIN" layout h_accordion </dev/null || echo "  layout change failed"

  echo "==== end collapse-to-1.sh ===="
  echo
} >>"$LOG" 2>&1

