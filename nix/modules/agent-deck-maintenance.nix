{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-maintenance;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-maintenance-runtime";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec" "$out/share/agent-deck-maintenance"
      install -m 0444 \
        ${../../private_dot_local/bin/private_executable_agent-deck-maintenance-controller} \
        "$out/libexec/agent-deck-maintenance-controller.py"
      install -m 0444 \
        ${../../private_dot_local/bin/private_executable_agent-deck-maintenance-collector} \
        "$out/libexec/agent-deck-maintenance-collector.py"
      install -m 0444 \
        ${../../docs/agent-deck-fleet-custodian-charter.md} \
        "$out/share/agent-deck-maintenance/fleet-custodian-charter.md"
      makeWrapper ${pkgs.python3}/bin/python3 \
        "$out/bin/agent-deck-maintenance-controller" \
        --add-flags "$out/libexec/agent-deck-maintenance-controller.py"
      makeWrapper ${pkgs.python3}/bin/python3 \
        "$out/bin/agent-deck-maintenance-collector" \
        --add-flags "$out/libexec/agent-deck-maintenance-collector.py"
      runHook postInstall
    '';
  };
  hostAlias = if cfg.hostAlias == null then "" else cfg.hostAlias;
  systemdLiteral = value: lib.replaceStrings [ "%" ] [ "%%" ] value;
  controllerArgs = [
    "${runtime}/bin/agent-deck-maintenance-controller"
    "--state"
    "%S/agent-deck-maintenance/${cfg.stateNamespace}/controller.json"
    "--collector-state"
    "%S/agent-deck-maintenance/${cfg.stateNamespace}/collector.json"
    "--state-namespace"
    cfg.stateNamespace
    "--report-root"
    "%S/agent-deck-maintenance-reports/${cfg.stateNamespace}"
    "--collector"
    "${runtime}/bin/agent-deck-maintenance-collector"
    "--agent-deck"
    (systemdLiteral cfg.agentDeckExecutable)
    "--codex-executable"
    (systemdLiteral cfg.codexExecutable)
    "--git"
    "${pkgs.git}/bin/git"
    "--charter"
    "${runtime}/share/agent-deck-maintenance/fleet-custodian-charter.md"
    "--workdir"
    (systemdLiteral cfg.workDirectory)
    "--host-alias"
    hostAlias
    "--profile"
    cfg.profileAlias
    "--full-survey-hours"
    (toString cfg.fullSurveyHours)
    "--warn-percent"
    (toString cfg.warnPercent)
    "--critical-percent"
    (toString cfg.criticalPercent)
    "--collector-timeout"
    (toString cfg.collectorTimeoutSeconds)
    "--agent-timeout"
    (toString cfg.agentTimeoutSeconds)
    "--report-timeout-hours"
    (toString cfg.reportTimeoutHours)
  ]
  ++ lib.concatMap (path: [
    "--repo"
    (systemdLiteral path)
  ]) cfg.repositoryRoots
  ++ lib.concatMap (path: [
    "--filesystem"
    (systemdLiteral path)
  ]) cfg.filesystemRoots;
in
{
  options.programs.agent-deck-maintenance = {
    enable = lib.mkEnableOption "the report-only Agent Deck maintenance controller";

    hostAlias = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "build-host";
      description = "Stable public-safe alias for the one host that owns this lifecycle.";
    };

    profileAlias = lib.mkOption {
      type = lib.types.str;
      default = "default";
      description = "One configured Agent Deck profile alias.";
    };

    stateNamespace = lib.mkOption {
      type = lib.types.str;
      default = "v3-default-report-only";
      description = "Versioned owner namespace shared by controller and collector state, separate from older deployments.";
    };

    workDirectory = lib.mkOption {
      type = lib.types.str;
      default = config.home.homeDirectory;
      description = "Existing directory in which the report-only custodian is launched.";
    };

    agentDeckExecutable = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.local/bin/agent-deck";
      description = "Absolute path to the public Agent Deck CLI.";
    };

    codexExecutable = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.npm-global/bin/codex";
      description = "Absolute path to the managed Codex CLI used for custodian sessions.";
    };

    repositoryRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Exact repository roots inspected read-only by the collector and custodian.";
    };

    filesystemRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "/" ];
      description = "Exact filesystem roots inspected read-only for capacity and bounded size.";
    };

    fullSurveyHours = lib.mkOption {
      type = lib.types.ints.between 1 8760;
      default = 24;
      description = "Cadence for a durably claimed full report-only survey.";
    };

    warnPercent = lib.mkOption {
      type = lib.types.ints.between 0 99;
      default = 80;
      description = "Collector warning-band lower bound.";
    };

    criticalPercent = lib.mkOption {
      type = lib.types.ints.between 1 100;
      default = 90;
      description = "Collector critical-band lower bound.";
    };

    collectorTimeoutSeconds = lib.mkOption {
      type = lib.types.ints.between 1 3600;
      default = 120;
      description = "Bound for one collector subprocess.";
    };

    agentTimeoutSeconds = lib.mkOption {
      type = lib.types.ints.between 1 3600;
      default = 600;
      description = "Bound for one exact Agent Deck launch, show, or send operation.";
    };

    reportTimeoutHours = lib.mkOption {
      type = lib.types.ints.between 1 8760;
      default = 24;
      description = "Deadline for a submitted report-only turn to produce its verified envelope.";
    };

    serviceTimeout = lib.mkOption {
      type = lib.types.str;
      default = "20m";
      description = "Systemd bound for the complete control tick.";
    };

    randomizedDelay = lib.mkOption {
      type = lib.types.str;
      default = "5m";
      description = "Randomized delay applied to the fixed hourly timer.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "programs.agent-deck-maintenance is supported only on Linux.";
      }
      {
        assertion =
          cfg.hostAlias != null && builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" cfg.hostAlias != null;
        message = "programs.agent-deck-maintenance.hostAlias must be a stable bounded alias.";
      }
      {
        assertion = builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" cfg.profileAlias != null;
        message = "programs.agent-deck-maintenance.profileAlias is invalid.";
      }
      {
        assertion = builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" cfg.stateNamespace != null;
        message = "programs.agent-deck-maintenance.stateNamespace is invalid.";
      }
      {
        assertion = cfg.warnPercent < cfg.criticalPercent;
        message = "programs.agent-deck-maintenance warning threshold must be below critical.";
      }
      {
        assertion = cfg.filesystemRoots != [ ];
        message = "programs.agent-deck-maintenance requires at least one filesystem root.";
      }
      {
        assertion = lib.all (path: lib.hasPrefix "/" path) (
          [
            cfg.workDirectory
            cfg.agentDeckExecutable
            cfg.codexExecutable
          ]
          ++ cfg.repositoryRoots
          ++ cfg.filesystemRoots
        );
        message = "programs.agent-deck-maintenance paths must be absolute.";
      }
    ];

    home.packages = [ runtime ];

    systemd.user.services.agent-deck-maintenance = {
      Unit = {
        Description = "Report-only Agent Deck maintenance control tick";
        ConditionFileIsExecutable = map systemdLiteral [
          cfg.agentDeckExecutable
          cfg.codexExecutable
        ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = lib.escapeShellArgs controllerArgs;
        TimeoutStartSec = cfg.serviceTimeout;
        UMask = "0077";
        StateDirectory = [ "agent-deck-maintenance" "agent-deck-maintenance-reports" ];
        StateDirectoryMode = "0700";
        NoNewPrivileges = true;
        # These remain best-effort namespace protections in user managers.
        # Do not add PrivateDevices, ProtectClock, ProtectKernelLogs, or
        # ProtectKernelModules: systemd implements them by narrowing the
        # capability bounding set, which an unprivileged user manager cannot
        # do when usable user namespaces are unavailable.
        ProtectControlGroups = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
        Environment = [
          (systemdLiteral "PATH=${config.home.homeDirectory}/.local/bin:${config.home.homeDirectory}/.npm-global/bin:${
            lib.makeBinPath [
              pkgs.coreutils
              pkgs.git
              pkgs.nodejs
              pkgs.tmux
              pkgs.bash
              pkgs.procps
            ]
          }")
        ];
      };
    };

    systemd.user.timers.agent-deck-maintenance = {
      Unit.Description = "Hourly report-only Agent Deck maintenance trigger";
      Timer = {
        OnCalendar = "hourly";
        Persistent = true;
        RandomizedDelaySec = cfg.randomizedDelay;
        AccuracySec = "1m";
        Unit = "agent-deck-maintenance.service";
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
