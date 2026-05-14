#!/usr/bin/env bash
set -euo pipefail

LOG="/tmp/aerospace-redistribute-debug.log"
TMP="/tmp/aerospace-redistribute-windows.txt"

{
  echo "==== redistribute-home-layout.sh: $(date) ===="
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
      app.zen-browser.zen|com.brave.Browser|com.apple.Safari|com.google.Chrome|com.google.Chrome.beta|company.thebrowser.Browser|com.todesktop.230313mzl4w4u92|com.microsoft.VSCode) echo 2; return 0;;
      com.mitchellh.ghostty|notion.id|com.linear) echo 3; return 0;;
    esac
    echo ""
  }

  monitor_connected() {
    local needle="$1"
    [[ -z "$needle" ]] && return 1
    while IFS=$'\t' read -r mon_name mon_id; do
      [[ -z "${mon_name//[[:space:]]/}" ]] && continue
      if [[ "$mon_name" == "$needle" ]]; then
        return 0
      fi
    done <<< "$monitor_inventory"
    return 1
  }

  monitor_id_for() {
    local needle="$1"
    [[ -z "$needle" ]] && return 1
    while IFS=$'\t' read -r mon_name mon_id; do
      [[ -z "${mon_name//[[:space:]]/}" ]] && continue
      if [[ "$mon_name" == "$needle" ]]; then
        printf '%s' "$mon_id"
        return 0
      fi
    done <<< "$monitor_inventory"
    return 1
  }

  ensure_workspace_monitor() {
    local ws="$1"
    local monitor="$2"
    if [[ -z "$monitor" ]]; then
      echo "  workspace ${ws} has no monitor mapping; skipping"
      return
    fi

    if monitor_connected "$monitor"; then
      local monitor_id=""
      monitor_id="$(monitor_id_for "$monitor" || true)"
      if [[ -z "$monitor_id" ]]; then
        echo "  failed to resolve monitor id for '${monitor}'"
        return
      fi
      if "$AEROSPACE_BIN" move-workspace-to-monitor --workspace "$ws" "$monitor_id" </dev/null; then
        echo "  workspace ${ws} pinned to '${monitor}'"
      else
        echo "  move-workspace-to-monitor FAILED for workspace ${ws} -> '${monitor}'"
      fi
    else
      echo "  monitor '${monitor}' unavailable; workspace ${ws} stays put"
    fi
  }

  monitor_inventory="$("$AEROSPACE_BIN" list-monitors --format $'%{monitor-name}%{tab}%{monitor-id}%{newline}' </dev/null 2>/dev/null || true)"
  echo "Currently connected monitors (name, id):"
  if [[ -n "${monitor_inventory//[[:space:]]/}" ]]; then
    while IFS=$'\t' read -r mon_name mon_id; do
      [[ -z "${mon_name//[[:space:]]/}" ]] && continue
      echo "  - ${mon_name} (id=${mon_id})"
    done <<< "$monitor_inventory"
  else
    echo "  (none reported)"
  fi
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
  echo "Flatten & balance workspaces 1,2,3..."
  for ws in 1 2 3; do
    "$AEROSPACE_BIN" flatten-workspace-tree --workspace "$ws" </dev/null || echo "  flatten failed for ws=$ws"
    "$AEROSPACE_BIN" balance-sizes --workspace "$ws" </dev/null || echo "  balance failed for ws=$ws"
  done

  echo
  echo "Rebinding workspaces to preferred monitors..."
  ensure_workspace_monitor 1 "Built-in Retina Display"
  ensure_workspace_monitor 2 "LG HDR 4K (1)"
  ensure_workspace_monitor 3 "LG HDR 4K (2)"

  echo
  echo "Resetting layouts to h_accordion..."
  for ws in 1 2 3; do
    if "$AEROSPACE_BIN" workspace "$ws" </dev/null; then
      "$AEROSPACE_BIN" layout h_accordion </dev/null || echo "  layout failed for ws=$ws"
    else
      echo "  workspace focus failed for ws=$ws"
    fi
  done

  echo
  echo "Focusing workspace 1 for Slack..."
  "$AEROSPACE_BIN" workspace 1 </dev/null || echo "  final workspace focus failed"

  echo "==== end redistribute-home-layout.sh ===="
  echo
} >>"$LOG" 2>&1

