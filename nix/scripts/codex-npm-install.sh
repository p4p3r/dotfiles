#!/usr/bin/env bash

# Install Codex only after its wrapper and native companion have been proven
# complete for this host. The caller supplies the managed npm prefix so the
# executable remains at PREFIX/bin/codex.

set -o pipefail

codex_log() {
  printf '%s\n' "$*"
}

codex_platform() {
  local operating_system machine

  operating_system="$(uname -s)" || return 1
  machine="$(uname -m)" || return 1
  case "$operating_system:$machine" in
    Linux:x86_64 | Linux:amd64)
      CODEX_PLATFORM_SUFFIX="linux-x64"
      ;;
    Linux:aarch64 | Linux:arm64)
      CODEX_PLATFORM_SUFFIX="linux-arm64"
      ;;
    Darwin:x86_64 | Darwin:amd64)
      CODEX_PLATFORM_SUFFIX="darwin-x64"
      ;;
    Darwin:aarch64 | Darwin:arm64)
      CODEX_PLATFORM_SUFFIX="darwin-arm64"
      ;;
    *)
      codex_log "ERROR: Codex npm updates do not support platform $operating_system/$machine."
      return 1
      ;;
  esac
  CODEX_PLATFORM_PACKAGE="@openai/codex-$CODEX_PLATFORM_SUFFIX"
}

codex_is_stable_version() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

codex_registry_version() {
  local package_spec="$1"
  local response version

  response="$(timeout 2m npm view "$package_spec" version --json 2>/dev/null)" || return 1
  version="$(jq -er 'if type == "string" then . else empty end' <<<"$response")" || return 1
  [[ -n "$version" ]] || return 1
  printf '%s\n' "$version"
}

codex_companion_is_published() {
  local candidate="$1"
  local expected="$candidate-$CODEX_PLATFORM_SUFFIX"
  local published

  published="$(codex_registry_version "@openai/codex@$expected")" || return 1
  [[ "$published" == "$expected" ]]
}

codex_executable_version() {
  local executable="$1"
  local output version

  [[ -x "$executable" ]] || return 1
  output="$("$executable" --version 2>/dev/null)" || return 1
  version="$(awk 'NR == 1 { print $NF }' <<<"$output")"
  codex_is_stable_version "$version" || return 1
  printf '%s\n' "$version"
}

codex_package_version_is() {
  local package_json="$1"
  local expected="$2"

  [[ -f "$package_json" ]] || return 1
  jq -e --arg expected "$expected" '.version == $expected' "$package_json" >/dev/null 2>&1
}

codex_installation_is_healthy() {
  local prefix="$1"
  local expected="$2"
  local root="$prefix/lib/node_modules/@openai/codex"
  local actual

  actual="$(codex_executable_version "$prefix/bin/codex")" || return 1
  [[ "$actual" == "$expected" ]] || return 1
  codex_package_version_is "$root/package.json" "$expected" || return 1
  codex_package_version_is \
    "$root/node_modules/$CODEX_PLATFORM_PACKAGE/package.json" \
    "$expected-$CODEX_PLATFORM_SUFFIX"
}

codex_install_exact() {
  local prefix="$1"
  local version="$2"

  timeout 15m npm install --global --prefix "$prefix" "@openai/codex@$version"
}

codex_qualify_candidate() {
  local candidate="$1"
  local temp_dir prefix status=0

  temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/codex-npm.XXXXXX")" || return 1
  prefix="$temp_dir/prefix"
  if ! codex_install_exact "$prefix" "$candidate" >/dev/null 2>&1; then
    status=1
  elif ! codex_installation_is_healthy "$prefix" "$candidate"; then
    status=1
  fi
  rm -rf "$temp_dir"
  return "$status"
}

codex_published_versions() {
  local response

  response="$(timeout 2m npm view @openai/codex versions --json 2>/dev/null)" || return 1
  jq -e 'type == "array"' <<<"$response" >/dev/null || return 1
  printf '%s\n' "$response"
}

codex_newest_complete_candidate() {
  local published candidate companion

  published="$(codex_published_versions)" || return 1
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    companion="$candidate-$CODEX_PLATFORM_SUFFIX"
    if jq -e --arg version "$companion" 'index($version) != null' \
      <<<"$published" >/dev/null \
      && codex_companion_is_published "$candidate" \
      && codex_qualify_candidate "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(
    jq -r '.[] | select(test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))' <<<"$published" \
      | sort --version-sort --reverse
  )
  return 1
}

codex_update_managed_prefix() {
  local live_prefix="$1"
  local codex="$live_prefix/bin/codex"
  local current="" latest candidate previous_healthy=""
  local qualification_failure=""

  if ! codex_platform; then
    return 1
  fi

  current="$(codex_executable_version "$codex")" || current=""
  if [[ -n "$current" ]] && codex_installation_is_healthy "$live_prefix" "$current"; then
    previous_healthy="$current"
  elif [[ -n "$current" ]]; then
    codex_log "Codex $current is installed but failed the platform-package health check."
  else
    codex_log "Codex is missing or broken at $codex."
  fi

  latest="$(codex_registry_version '@openai/codex@latest')" || {
    codex_log "ERROR: Could not resolve a concrete latest Codex npm version."
    return 1
  }
  if ! codex_is_stable_version "$latest"; then
    codex_log "ERROR: Refusing unexpected latest Codex version '$latest'."
    return 1
  fi

  if [[ -n "$previous_healthy" && "$previous_healthy" == "$latest" ]]; then
    codex_log "Codex is current and healthy at $previous_healthy."
    return 0
  fi

  candidate="$latest"
  if ! codex_companion_is_published "$candidate"; then
    qualification_failure="the exact $CODEX_PLATFORM_PACKAGE companion is not published"
  elif ! codex_qualify_candidate "$candidate"; then
    qualification_failure="isolated installation did not produce a healthy executable and platform package"
  fi

  if [[ -n "$qualification_failure" ]]; then
    if [[ -n "$previous_healthy" ]]; then
      codex_log "Deferring Codex $latest: $qualification_failure; retaining healthy Codex $previous_healthy."
      return 0
    fi
    codex_log "Codex $latest is incomplete for $CODEX_PLATFORM_SUFFIX; searching for the newest complete stable version."
    candidate="$(codex_newest_complete_candidate)" || {
      codex_log "ERROR: No complete stable Codex version could be qualified for $CODEX_PLATFORM_SUFFIX."
      return 1
    }
    codex_log "Recovering broken Codex with complete version $candidate."
  fi

  codex_log "Installing qualified Codex $candidate into $live_prefix."
  if codex_install_exact "$live_prefix" "$candidate" >/dev/null 2>&1 \
    && codex_installation_is_healthy "$live_prefix" "$candidate"; then
    codex_log "Codex $candidate is installed and healthy with $CODEX_PLATFORM_PACKAGE."
    return 0
  fi

  codex_log "ERROR: Live Codex $candidate installation or verification failed."
  if [[ -z "$previous_healthy" ]]; then
    codex_log "ERROR: No previously healthy Codex version is available for rollback."
    return 1
  fi

  codex_log "Restoring previously healthy Codex $previous_healthy."
  if ! codex_install_exact "$live_prefix" "$previous_healthy" >/dev/null 2>&1; then
    codex_log "ERROR: npm failed while restoring Codex $previous_healthy; verifying the live prefix anyway."
  fi
  if codex_installation_is_healthy "$live_prefix" "$previous_healthy"; then
    codex_log "Codex $previous_healthy was restored and proven healthy."
    return 1
  fi

  codex_log "ERROR: Rollback failed; no healthy live Codex installation could be proven."
  return 1
}

codex_main() {
  local command="${1:-}"

  case "$command" in
    update | ensure)
      if [[ $# -ne 2 || -z "$2" ]]; then
        codex_log "Usage: $0 $command PREFIX"
        return 2
      fi
      codex_update_managed_prefix "$2"
      ;;
    platform)
      if [[ $# -ne 1 ]]; then
        codex_log "Usage: $0 platform"
        return 2
      fi
      codex_platform || return 1
      printf '%s %s\n' "$CODEX_PLATFORM_PACKAGE" "$CODEX_PLATFORM_SUFFIX"
      ;;
    *)
      codex_log "Usage: $0 {update|ensure} PREFIX"
      return 2
      ;;
  esac
}

codex_main "$@"
