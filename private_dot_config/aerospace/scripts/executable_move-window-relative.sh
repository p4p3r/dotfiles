#!/usr/bin/env bash
set -euo pipefail

DIR="${1:-}"
case "$DIR" in
  prev|next) ;;
  *)
    echo "Usage: $0 prev|next" >&2
    exit 1
    ;;
esac

AEROSPACE_BIN="${AEROSPACE_BIN:-$(command -v aerospace || true)}"
if [[ -z "$AEROSPACE_BIN" ]]; then
  echo "ERROR: aerospace binary not found in PATH" >&2
  exit 1
fi

current_ws="$("$AEROSPACE_BIN" list-windows --focused --format $'%{workspace}%{newline}' 2>/dev/null | head -n 1 || true)"
if [[ -z "${current_ws//[[:space:]]/}" ]]; then
  # Nothing focused, nothing to move
  exit 0
fi

order=("1" "2" "3")
idx=-1
for i in "${!order[@]}"; do
  if [[ "${order[$i]}" == "$current_ws" ]]; then
    idx="$i"
    break
  fi
done

if (( idx < 0 )); then
  # Workspace outside the predefined trio; nothing to do
  exit 0
fi

count="${#order[@]}"
if [[ "$DIR" == "next" ]]; then
  target_index=$(( (idx + 1) % count ))
else
  target_index=$(( (idx - 1 + count) % count ))
fi

target_ws="${order[$target_index]}"

"$AEROSPACE_BIN" move-node-to-workspace --focus-follows-window "$target_ws" </dev/null || true

