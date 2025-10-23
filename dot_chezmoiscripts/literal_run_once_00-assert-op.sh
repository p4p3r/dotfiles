#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
  exit 0
fi

if ! command -v op >/dev/null 2>&1; then
  echo "[bootstrap] 1Password CLI 'op' not found. Install it first (Phase 0)." >&2
  exit 1
fi

if ! op whoami >/dev/null 2>&1; then
  echo "[bootstrap] Please run 'op account add' (if needed) and 'eval "$(op signin)"' before 'chezmoi apply'." >&2
  exit 1
fi
