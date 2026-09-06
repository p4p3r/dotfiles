{
  config,
  lib,
  pkgs,
  ...
}:
let
  updater = pkgs.writeShellApplication {
    name = "agent-cli-update";
    runtimeInputs = with pkgs; [
      coreutils
      curl
      gawk
      gnugrep
      gzip
      jq
      nodejs_22
      procps
      systemd
      gnutar
      util-linux
    ];
    text = ''
      export HOME="${config.home.homeDirectory}"
      export NPM_CONFIG_PREFIX="$HOME/.npm-global"
      export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

      state_dir="$HOME/.cache/agent-cli-update"
      restart_marker="$state_dir/restart-agent-deck-services"
      deferred_marker="$state_dir/deferred-agent-deck-release"
      mkdir -p "$state_dir"

      exec 9>"$state_dir/update.lock"
      if ! flock -n 9; then
        printf '%s\n' "Another CLI update run is active; exiting."
        exit 0
      fi

      result=0

      log() {
        printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
      }

      run_update() {
        local label="$1"
        shift
        log "Updating $label..."
        if timeout 15m "$@"; then
          log "$label update completed."
        else
          local status=$?
          log "ERROR: $label update failed with status $status."
          return "$status"
        fi
      }

      update_claude() {
        local claude="$HOME/.local/bin/claude"
        if [[ ! -x "$claude" ]]; then
          log "ERROR: Claude Code is missing at $claude."
          return 1
        fi
        run_update "Claude Code" "$claude" update
      }

      update_codex() {
        local codex="$HOME/.npm-global/bin/codex"
        local current latest
        if [[ ! -x "$codex" ]]; then
          log "ERROR: Codex is missing at $codex."
          return 1
        fi
        if ! current="$("$codex" --version | awk 'NR == 1 { print $NF }')"; then
          log "ERROR: Could not read the installed Codex version."
          return 1
        fi
        if ! latest="$(timeout 2m npm view @openai/codex version | tail -n 1)"; then
          log "ERROR: Could not resolve the latest Codex npm version."
          return 1
        fi
        if [[ -z "$current" || -z "$latest" ]]; then
          log "ERROR: Empty Codex version (installed='$current', latest='$latest')."
          return 1
        fi
        if [[ "$current" == "$latest" ]]; then
          log "Codex is current at $current."
          return 0
        fi
        run_update "Codex $current -> $latest" npm install --global @openai/codex@latest
      }

      check_agent_deck_feature() {
        local source_dir="$1"
        local relative_path="$2"
        local needle="$3"
        local description="$4"
        if [[ ! -f "$source_dir/$relative_path" ]] ||
          ! grep -Fq -- "$needle" "$source_dir/$relative_path"; then
          log "Agent Deck safety gate missing: $description ($relative_path)."
          return 1
        fi
      }

      agent_deck_release_is_safe() {
        local source_dir="$1"
        local gate_ok=0

        check_agent_deck_feature "$source_dir" \
          "internal/session/codex_output.go" \
          'event.Payload.Phase != "final_answer"' \
          "structured Codex final-answer extraction" || gate_ok=1
        check_agent_deck_feature "$source_dir" \
          "cmd/agent-deck/session_cmd.go" \
          'freshWait = *timeout' \
          "full-timeout Codex fresh-output wait" || gate_ok=1
        check_agent_deck_feature "$source_dir" \
          "internal/tmux/detector.go" \
          'HasCodexBusyIndicator(content)' \
          "status-line-shaped Codex busy detection" || gate_ok=1
        check_agent_deck_feature "$source_dir" \
          "internal/session/conductor_bridge.py" \
          'conductor_agent_command(name),' \
          "runtime-aware conductor recreation" || gate_ok=1
        check_agent_deck_feature "$source_dir" \
          "internal/session/conductor_bridge.py" \
          'codex output freshness timeout' \
          "async late-reply handling for long Codex turns" || gate_ok=1

        return "$gate_ok"
      }

      update_agent_deck() {
        local agent_deck="$HOME/.local/bin/agent-deck"
        local bridge="$HOME/.local/share/agent-deck/conductor/bridge.py"
        local release_json tag current latest highest
        local temp_dir source_dir before_sha after_sha

        if [[ ! -x "$agent_deck" ]]; then
          log "ERROR: Agent Deck is missing at $agent_deck."
          return 1
        fi
        if ! current="$("$agent_deck" --version | awk 'NR == 1 { version=$NF; sub(/^v/, "", version); print version }')"; then
          log "ERROR: Could not read the installed Agent Deck version."
          return 1
        fi
        if ! release_json="$(timeout 2m curl --fail --silent --show-error --location \
          https://api.github.com/repos/asheshgoplani/agent-deck/releases/latest)"; then
          log "ERROR: Could not query the latest Agent Deck release."
          return 1
        fi
        tag="$(jq -r '.tag_name // empty' <<<"$release_json")"
        if [[ ! "$tag" =~ ^v[0-9]+([.][0-9]+){1,3}([A-Za-z0-9._-]*)?$ ]]; then
          log "ERROR: Refusing unexpected Agent Deck release tag '$tag'."
          return 1
        fi
        latest="''${tag#v}"
        if [[ "$current" == "$latest" ]]; then
          rm -f "$deferred_marker"
          log "Agent Deck is current at $current."
          return 0
        fi
        highest="$(printf '%s\n%s\n' "$current" "$latest" | sort --version-sort | tail -n 1)"
        if [[ "$highest" != "$latest" ]]; then
          log "Agent Deck $current is newer than published release $latest; leaving it unchanged."
          return 0
        fi

        temp_dir="$(mktemp -d "$state_dir/release.XXXXXX")"
        source_dir="$temp_dir/source"
        mkdir -p "$source_dir"
        if ! timeout 5m curl --fail --silent --show-error --location --retry 3 \
          "https://github.com/asheshgoplani/agent-deck/archive/refs/tags/$tag.tar.gz" \
          -o "$temp_dir/source.tar.gz"; then
          rm -rf "$temp_dir"
          log "ERROR: Could not download Agent Deck $tag source for the safety gate."
          return 1
        fi
        if ! tar --extract --gzip --file "$temp_dir/source.tar.gz" \
          --directory "$source_dir" --strip-components=1; then
          rm -rf "$temp_dir"
          log "ERROR: Could not extract Agent Deck $tag source for the safety gate."
          return 1
        fi
        if ! agent_deck_release_is_safe "$source_dir"; then
          printf '%s\n' "$tag" >"$deferred_marker"
          rm -rf "$temp_dir"
          log "Deferring Agent Deck $tag: it would regress this host's Codex remote-control fixes."
          return 0
        fi
        rm -rf "$temp_dir"

        before_sha="$(sha256sum "$agent_deck" | awk '{ print $1 }')"
        cp -p "$agent_deck" "$state_dir/agent-deck-$current"
        if [[ -f "$bridge" ]]; then
          cp -p "$bridge" "$state_dir/bridge-$current.py"
        fi

        log "Updating Agent Deck $current -> $latest after safety-gate approval..."
        if ! printf '\n' | timeout 15m "$agent_deck" update; then
          log "ERROR: Agent Deck update failed; backup remains in $state_dir."
          return 1
        fi
        after_sha="$(sha256sum "$agent_deck" | awk '{ print $1 }')"
        if [[ "$before_sha" == "$after_sha" ]]; then
          log "ERROR: Agent Deck reported success but its binary did not change."
          return 1
        fi

        rm -f "$deferred_marker"
        touch "$restart_marker"
        log "Agent Deck updated to $latest; service restart is pending an idle remote-control bridge."
      }

      restart_agent_deck_services_when_idle() {
        local unit restarted=0
        if [[ ! -e "$restart_marker" ]]; then
          return 0
        fi
        if pgrep -f '(^|/)[a]gent-deck .*session send .*--wait' >/dev/null; then
          log "Deferring Agent Deck service restart while a blocking remote-control send is active."
          return 0
        fi

        for unit in agent-deck-conductor-bridge.service agent-deck-transition-notifier.service; do
          if systemctl --user is-active --quiet "$unit"; then
            log "Restarting $unit after the Agent Deck update..."
            if systemctl --user restart "$unit"; then
              restarted=1
            else
              log "ERROR: Could not restart $unit."
              return 1
            fi
          fi
        done
        rm -f "$restart_marker"
        log "Agent Deck service refresh completed (active units restarted: $restarted)."
      }

      log "Starting hourly CLI update check."
      update_claude || result=1
      update_codex || result=1
      update_agent_deck || result=1
      restart_agent_deck_services_when_idle || result=1
      log "Hourly CLI update check finished with status $result."
      exit "$result"
    '';
  };
in
{
  systemd.user.services.agent-cli-update = lib.mkIf pkgs.stdenv.isLinux {
    Unit = {
      Description = "Update Claude Code, Codex, and Agent Deck";
      Wants = [ "network-online.target" ];
      After = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${updater}/bin/agent-cli-update";
      TimeoutStartSec = "45m";
    };
  };

  systemd.user.timers.agent-cli-update = lib.mkIf pkgs.stdenv.isLinux {
    Unit.Description = "Hourly Claude Code, Codex, and Agent Deck updates";
    Timer = {
      OnCalendar = "hourly";
      Persistent = true;
      RandomizedDelaySec = "10m";
      AccuracySec = "1m";
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
