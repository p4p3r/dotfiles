{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-channel-liveness;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-channel-liveness-runtime";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec"
      install -m 0444 \
        ${../../private_dot_local/bin/executable_agent-deck-channel-liveness} \
        "$out/libexec/agent-deck-channel-liveness.py"
      makeWrapper ${pkgs.python3}/bin/python3 \
        "$out/bin/agent-deck-channel-liveness" \
        --add-flags "$out/libexec/agent-deck-channel-liveness.py"
      runHook postInstall
    '';
  };
  systemdLiteral = value: lib.replaceStrings [ "%" ] [ "%%" ] value;
  arguments = [
    "${runtime}/bin/agent-deck-channel-liveness"
    "--unit"
    cfg.unit
    "--database"
    (systemdLiteral cfg.database)
    "--state-dir"
    "%S/agent-deck-channel-liveness/${cfg.stateNamespace}"
    "--systemctl"
    "/usr/bin/systemctl"
    "--max-silence-minutes"
    (toString cfg.maxSilenceMinutes)
    "--daily-restart-cap"
    (toString cfg.dailyRestartCap)
  ]
  ++ lib.optional cfg.apply "--apply";
in
{
  options.programs.agent-deck-channel-liveness = {
    enable = lib.mkEnableOption "the channel conductor inbound liveness monitor";

    unit = lib.mkOption {
      type = lib.types.str;
      description = "User unit whose inbound path is watched.";
    };

    database = lib.mkOption {
      type = lib.types.str;
      description = ''
        Absolute path to the conductor's gateway database. It is copied before
        being read, so the monitor never takes a lock on what it monitors.
      '';
    };

    stateNamespace = lib.mkOption {
      type = lib.types.str;
      description = "Owner namespace for the restart ledger.";
    };

    maxSilenceMinutes = lib.mkOption {
      type = lib.types.ints.positive;
      default = 45;
      description = ''
        Silence after which the unit is recycled. A quiet channel and a dead
        socket are indistinguishable locally, so this is a recycle threshold
        rather than a diagnosis: long enough that a normal lull does not trip
        it, short enough that an outage is measured in minutes.
      '';
    };

    dailyRestartCap = lib.mkOption {
      type = lib.types.ints.positive;
      default = 6;
      description = "Restarts allowed per rolling day, so a broken unit cannot flap.";
    };

    apply = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Perform restarts. False reports the verdict and acts on nothing.";
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "*:0/10";
      description = "systemd OnCalendar expression for the liveness check.";
    };

    armTimer = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Install the timer into timers.target.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "programs.agent-deck-channel-liveness is supported only on Linux.";
      }
      {
        assertion = lib.hasPrefix "/" cfg.database;
        message = "programs.agent-deck-channel-liveness.database must be absolute.";
      }
      {
        assertion = cfg.maxSilenceMinutes >= 5;
        message = "programs.agent-deck-channel-liveness.maxSilenceMinutes must be at least 5.";
      }
    ];

    home.packages = [ runtime ];

    systemd.user.services.agent-deck-channel-liveness = {
      Unit.Description = "Channel conductor inbound liveness check";
      Service = {
        Type = "oneshot";
        ExecStart = lib.escapeShellArgs arguments;
        TimeoutStartSec = "5min";
        UMask = "0077";
        StateDirectory = [ "agent-deck-channel-liveness" ];
        StateDirectoryMode = "0700";
        NoNewPrivileges = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
        Environment = [
          (systemdLiteral "PATH=${lib.makeBinPath [ pkgs.coreutils ]}")
        ];
      };
    };

    systemd.user.timers.agent-deck-channel-liveness = {
      Unit.Description = "Scheduled channel conductor liveness check";
      Timer = {
        OnCalendar = cfg.schedule;
        Persistent = false;
        AccuracySec = "30s";
        Unit = "agent-deck-channel-liveness.service";
      };
      Install.WantedBy = lib.optional cfg.armTimer "timers.target";
    };
  };
}
