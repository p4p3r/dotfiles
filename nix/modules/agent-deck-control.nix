{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-control;
  unit = "agent-deck-conductor-tick-${cfg.profileName}-${cfg.conductorName}";
  literal = value: lib.replaceStrings [ "%" ] [ "%%" ] value;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-control-runtime";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec" "$out/share/agent-deck-control"
      install -m 0444 ${../../private_dot_local/bin/executable_agent-deck-conductor-tick} \
        "$out/libexec/agent-deck-conductor-tick.py"
      install -m 0444 ${../../private_dot_local/bin/private_executable_agent-deck-work-registry} \
        "$out/libexec/agent-deck-work-registry.py"
      install -m 0444 ${../../docs/agent-deck-conductor-tick.md} \
        "$out/share/agent-deck-control/conductor-tick.md"
      makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/agent-deck-work-registry" \
        --add-flags "$out/libexec/agent-deck-work-registry.py"
      makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/agent-deck-conductor-tick" \
        --add-flags "$out/libexec/agent-deck-conductor-tick.py"
      runHook postInstall
    '';
  };
  args = [
    "${runtime}/bin/agent-deck-conductor-tick"
    "--registry"
    "${runtime}/bin/agent-deck-work-registry"
    "--state"
    (literal cfg.registryState)
    "--agent-deck"
    (literal cfg.agentDeckExecutable)
    "--profile"
    cfg.profileName
    "--max-polls"
    (toString cfg.maxPolls)
    "--poll-timeout"
    (toString cfg.pollTimeoutSeconds)
    "--budget-seconds"
    "80"
  ];
in
{
  options.programs.agent-deck-control = {
    enable = lib.mkEnableOption "one conductor-owned metadata reconciliation timer";

    profileName = lib.mkOption {
      type = lib.types.str;
      default = "default";
      description = "Exact local Agent Deck profile that owns this registry.";
    };

    conductorName = lib.mkOption {
      type = lib.types.str;
      default = "default";
      description = "Bounded local conductor alias used to name this single timer.";
    };

    registryState = lib.mkOption {
      type = lib.types.str;
      default = "${config.xdg.stateHome}/agent-deck-control/${cfg.profileName}/${cfg.conductorName}.json";
      description = "Absolute path to the one conductor-owned registry; never copied between hosts.";
    };

    agentDeckExecutable = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.local/bin/agent-deck";
      description = "Absolute path to the read-only Agent Deck metadata CLI.";
    };

    maxPolls = lib.mkOption {
      type = lib.types.ints.between 1 12;
      default = 12;
      description = "Maximum selected records per tick; older records lead the next tick.";
    };

    pollTimeoutSeconds = lib.mkOption {
      type = lib.types.ints.between 1 5;
      default = 5;
      description = "Poll deadline; a timeout persists an unknown observation.";
    };

    cadenceSeconds = lib.mkOption {
      type = lib.types.ints.between 30 86400;
      default = 120;
      description = "Delay after a finished tick before polling again.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "programs.agent-deck-control is supported only on Linux.";
      }
      {
        assertion = lib.all (value: builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,63}" value != null) [
          cfg.profileName
          cfg.conductorName
        ];
        message = "programs.agent-deck-control profile and conductor aliases are invalid.";
      }
      {
        assertion = lib.all (path: lib.hasPrefix "/" path) [
          cfg.registryState
          cfg.agentDeckExecutable
        ];
        message = "programs.agent-deck-control paths must be absolute.";
      }
    ];

    home.packages = [ runtime ];

    systemd.user.services.${unit} = {
      Unit = {
        Description = "Bounded conductor work-registry metadata tick";
        ConditionFileIsExecutable = literal cfg.agentDeckExecutable;
      };
      Service = {
        Type = "oneshot";
        ExecStart = lib.escapeShellArgs args;
        TimeoutStartSec = "90s";
        Restart = "no";
        KillMode = "control-group";
        UMask = "0077";
        StateDirectory = "agent-deck-control/${cfg.profileName}";
        StateDirectoryMode = "0700";
        Environment = [
          "AGENTDECK_SKIP_UPDATE_CHECK=1"
          "PYTHONDONTWRITEBYTECODE=1"
        ];
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ReadWritePaths = literal (builtins.dirOf cfg.registryState);
      };
    };

    systemd.user.timers.${unit} = {
      Unit.Description = "Conductor-owned metadata reconciliation cadence";
      Timer = {
        OnBootSec = "30s";
        OnUnitInactiveSec = "${toString cfg.cadenceSeconds}s";
        AccuracySec = "5s";
        Unit = "${unit}.service";
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
