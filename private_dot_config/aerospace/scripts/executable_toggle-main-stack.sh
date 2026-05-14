#!/usr/bin/env bash
set -euo pipefail

LOG="/tmp/aerospace-main-stack.log"
STATE_DIR="${HOME}/.config/aerospace/state"
mkdir -p "$STATE_DIR"

{
  echo "==== toggle-main-stack: $(date) ===="
  AEROSPACE_BIN="${AEROSPACE_BIN:-$(command -v aerospace || true)}"
  if [[ -z "${AEROSPACE_BIN}" ]]; then
    echo "ERROR: aerospace binary not found in PATH"
    exit 1
  fi

  current_ws="$("$AEROSPACE_BIN" list-windows --focused --format $'%{workspace}%{newline}' 2>/dev/null | head -n 1 || true)"
  if [[ -z "${current_ws//[[:space:]]/}" ]]; then
    echo "No focused workspace/windows; nothing to do."
    exit 0
  fi
  echo "Workspace=${current_ws}"

  focused_win="$("$AEROSPACE_BIN" list-windows --focused --format $'%{window-id}%{newline}' 2>/dev/null | head -n 1 || true)"
  if [[ -z "${focused_win//[[:space:]]/}" ]]; then
    echo "No focused window; defaulting to first window later."
  fi

  # Collect window ids on the current workspace (preserve DFS order)
  windows=()
  stack_ids=()
  while IFS=$'\t' read -r win_id _; do
    [[ -z "${win_id//[[:space:]]/}" ]] && continue
    windows+=("$win_id")
    if [[ -n "${focused_win}" && "$win_id" == "$focused_win" ]]; then
      continue
    fi
    stack_ids+=("$win_id")
  done < <("$AEROSPACE_BIN" list-windows --workspace "$current_ws" --format $'%{window-id}%{tab}%{app-bundle-id}%{newline}' 2>/dev/null || true)

  if [[ ${#windows[@]} -eq 0 ]]; then
    echo "No tiled windows on workspace ${current_ws}; exiting."
    exit 0
  fi

  if [[ -z "$focused_win" ]]; then
    focused_win="${windows[0]}"
    stack_ids=("${windows[@]:1}")
  fi

  state_file="${STATE_DIR}/workspace-${current_ws}-main-stack.state"
  current_state="$(cat "$state_file" 2>/dev/null || echo "accordion")"
  echo "Previously recorded state=${current_state}"

  revert_to_accordion() {
    echo "Reverting to accordion layout..."
    "$AEROSPACE_BIN" flatten-workspace-tree --workspace "$current_ws" </dev/null || true
    "$AEROSPACE_BIN" layout h_accordion </dev/null || true
    "$AEROSPACE_BIN" balance-sizes --workspace "$current_ws" </dev/null || true
    "$AEROSPACE_BIN" focus --window-id "$focused_win" </dev/null || true
    echo "accordion" >"$state_file"
  }

  build_main_stack() {
    echo "Building main/stack layout..."
    if [[ ${#windows[@]} -le 1 ]]; then
      echo "Only one window; keeping tiles layout."
      "$AEROSPACE_BIN" flatten-workspace-tree --workspace "$current_ws" </dev/null || true
      "$AEROSPACE_BIN" layout h_tiles </dev/null || true
      "$AEROSPACE_BIN" focus --window-id "$focused_win" </dev/null || true
      echo "stack" >"$state_file"
      return
    fi

    tmp_ws="__mainstack_tmp_${current_ws}"
    echo "Moving ${#stack_ids[@]} stack windows to ${tmp_ws} temporarily..."
    for win in "${stack_ids[@]}"; do
      "$AEROSPACE_BIN" move-node-to-workspace --window-id "$win" "$tmp_ws" </dev/null || true
    done

    "$AEROSPACE_BIN" workspace "$current_ws" </dev/null || true
    "$AEROSPACE_BIN" flatten-workspace-tree --workspace "$current_ws" </dev/null || true
    "$AEROSPACE_BIN" layout h_tiles </dev/null || true
    "$AEROSPACE_BIN" focus --window-id "$focused_win" </dev/null || true

    echo "Restoring stack windows..."
    for win in "${stack_ids[@]}"; do
      "$AEROSPACE_BIN" move-node-to-workspace --window-id "$win" "$current_ws" </dev/null || true
    done

    if [[ ${#stack_ids[@]} -ge 2 ]]; then
      for ((idx=1; idx<${#stack_ids[@]}; idx++)); do
        win="${stack_ids[$idx]}"
        "$AEROSPACE_BIN" focus --window-id "$win" </dev/null || true
        "$AEROSPACE_BIN" join-with left </dev/null || true
      done
    fi

    if [[ ${#stack_ids[@]} -ge 1 ]]; then
      "$AEROSPACE_BIN" focus --window-id "${stack_ids[0]}" </dev/null || true
      "$AEROSPACE_BIN" layout v_tiles </dev/null || true
    fi

    "$AEROSPACE_BIN" focus --window-id "$focused_win" </dev/null || true
    main_delta="${MAIN_STACK_INITIAL_RESIZE:-500}"
    echo "Expanding main pane by ${main_delta}px (override with MAIN_STACK_INITIAL_RESIZE)..."
    "$AEROSPACE_BIN" resize smart "+${main_delta}" </dev/null || true
    echo "stack" >"$state_file"
  }

  if [[ "$current_state" == "stack" ]]; then
    revert_to_accordion
  else
    build_main_stack
  fi
} >>"$LOG" 2>&1

