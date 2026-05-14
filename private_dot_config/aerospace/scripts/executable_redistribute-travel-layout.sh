#!/usr/bin/env bash
set -euo pipefail

LOG="/tmp/aerospace-redistribute-debug.log"
TMP="/tmp/aerospace-redistribute-windows.txt"

{
  echo "==== redistribute-travel-layout.sh: $(date) ===="
  echo "PATH=$PATH"

  AEROSPACE_BIN="${AEROSPACE_BIN:-$(command -v aerospace || true)}"
  echo "AEROSPACE_BIN='$AEROSPACE_BIN'"

  if [[ -z "${AEROSPACE_BIN}" ]]; then
    echo "ERROR: aerospace binary not found in PATH"
    exit 1
  fi

  # Dump the windows into TMP
  "$AEROSPACE_BIN" list-windows --all --format $'%{window-id}%{tab}%{app-bundle-id}%{tab}%{workspace}%{tab}%{monitor-name}%{newline}' > "$TMP" || true
  echo "Raw output (first 200 lines):"
  sed -n '1,200p' "$TMP" || true
  echo "Total lines: $(wc -l < "$TMP" 2>/dev/null || true)"
  echo

  target_ws_for() {
    local bundle="$1"
    case "$bundle" in
      com.tinyspeck.slackmacgap) echo 1; return 0;;
      *) echo 2; return 0;;  # Travel mode: everything else goes to the external monitor
    esac
  }

  monitor_inventory="$("$AEROSPACE_BIN" list-monitors --format $'%{monitor-name}%{tab}%{monitor-id}%{newline}' </dev/null 2>/dev/null || true)"
  echo "Currently connected monitors (name, id):"

  # Find the external monitor (first non-built-in)
  external_monitor_id=""
  external_monitor_name=""
  while IFS=$'\t' read -r mon_name mon_id; do
    [[ -z "${mon_name//[[:space:]]/}" ]] && continue
    echo "  - ${mon_name} (id=${mon_id})"
    if [[ "$mon_name" != "Built-in Retina Display" && -z "$external_monitor_id" ]]; then
      external_monitor_id="$mon_id"
      external_monitor_name="$mon_name"
    fi
  done <<< "$monitor_inventory"
  echo
  echo "External monitor: '${external_monitor_name}' (id=${external_monitor_id})"
  echo

  echo "Deciding targets & moving…"
  while IFS=$'\t' read -r win_id bundle ws mon; do
    [[ -z "${win_id//[[:space:]]/}" ]] && continue
    target_ws="$(target_ws_for "${bundle:-}")"
    echo "  window ${win_id} (bundle='${bundle:-}' ws='${ws:-}' mon='${mon:-}') -> target='${target_ws}'"

    if [[ -n "$target_ws" ]]; then
      if "$AEROSPACE_BIN" move-node-to-workspace --window-id "$win_id" "$target_ws" </dev/null; then
        echo "    moved ${win_id} -> ${target_ws}"
      else
        echo "    move FAILED for ${win_id}"
      fi
    else
      echo "    skipping ${win_id} (no rule)"
    fi
  done < "$TMP"

  echo
  echo "Flatten & balance workspaces 1,2..."
  for ws in 1 2; do
    "$AEROSPACE_BIN" flatten-workspace-tree --workspace "$ws" </dev/null || echo "  flatten failed for ws=$ws"
    "$AEROSPACE_BIN" balance-sizes --workspace "$ws" </dev/null || echo "  balance failed for ws=$ws"
  done

  echo
  echo "Binding workspace 1 to laptop, workspace 2 to external monitor..."

  # Workspace 1 -> laptop
  if "$AEROSPACE_BIN" move-workspace-to-monitor --workspace 1 "Built-in Retina Display" </dev/null 2>/dev/null; then
    echo "  workspace 1 pinned to Built-in Retina Display"
  else
    echo "  workspace 1 pin failed (may already be there)"
  fi

  # Workspace 2 -> external monitor
  if [[ -n "$external_monitor_id" ]]; then
    if "$AEROSPACE_BIN" move-workspace-to-monitor --workspace 2 "$external_monitor_id" </dev/null; then
      echo "  workspace 2 pinned to '${external_monitor_name}'"
    else
      echo "  move-workspace-to-monitor FAILED for workspace 2"
    fi
  else
    echo "  no external monitor found; workspace 2 stays put"
  fi

  echo
  echo "Resetting layouts to h_accordion..."
  for ws in 1 2; do
    if "$AEROSPACE_BIN" workspace "$ws" </dev/null; then
      "$AEROSPACE_BIN" layout h_accordion </dev/null || echo "  layout failed for ws=$ws"
    else
      echo "  workspace focus failed for ws=$ws"
    fi
  done

  echo
  echo "Focusing workspace 2 on external monitor..."
  "$AEROSPACE_BIN" workspace 2 </dev/null || echo "  final workspace focus failed"

  echo "==== end redistribute-travel-layout.sh ===="
  echo
} >>"$LOG" 2>&1
