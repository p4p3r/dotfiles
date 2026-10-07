{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-slack-watchdog;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-slack-watchdog";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec"
      install -m 0444 \
        ${../../private_dot_local/bin/executable_agent-deck-slack-watchdog} \
        "$out/libexec/agent-deck-slack-watchdog.py"
      makeWrapper ${pkgs.python3}/bin/python3 \
        "$out/bin/agent-deck-slack-watchdog" \
        --add-flags "$out/libexec/agent-deck-slack-watchdog.py"
      runHook postInstall
    '';
  };
  settingsFile = if cfg.settingsFile == null then "" else cfg.settingsFile;
  systemdLiteral = value: lib.replaceStrings [ "%" ] [ "%%" ] value;
in
{
  options.programs.agent-deck-slack-watchdog = {
    enable = lib.mkEnableOption "the fail-closed Agent Deck Slack gateway watchdog";

    settingsFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/home/example/.config/agent-deck/slack-watchdog.json";
      description = ''
        Absolute path to an owner-only runtime settings file. The file pins the
        gateway control socket, systemd unit, binary/config/row-binding
        incarnation, and bounded control/restart timeouts. It must not live in
        the Nix store.
      '';
    };

    interval = lib.mkOption {
      type = lib.types.str;
      default = "1m";
      description = "Delay between completed watchdog probes.";
    };

    randomizedDelay = lib.mkOption {
      type = lib.types.str;
      default = "10s";
      description = "Bounded randomized delay for each watchdog probe.";
    };

    serviceTimeout = lib.mkOption {
      type = lib.types.str;
      default = "30s";
      description = "Systemd bound for the complete probe and possible one-shot recovery.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "programs.agent-deck-slack-watchdog is supported only on Linux.";
      }
      {
        assertion = cfg.settingsFile != null && lib.hasPrefix "/" cfg.settingsFile;
        message = "programs.agent-deck-slack-watchdog.settingsFile must be an absolute non-store path.";
      }
      {
        assertion = cfg.settingsFile == null || !(lib.hasPrefix "/nix/store/" cfg.settingsFile);
        message = "programs.agent-deck-slack-watchdog.settingsFile must not expose runtime pins through the Nix store.";
      }
    ];

    home.packages = [ runtime ];

    systemd.user.services.agent-deck-slack-watchdog = {
      Unit = {
        Description = "Fail-closed Agent Deck Slack gateway watchdog";
        ConditionPathExists = systemdLiteral settingsFile;
      };
      Service = {
        Type = "oneshot";
        ExecStart = lib.escapeShellArgs [
          "${runtime}/bin/agent-deck-slack-watchdog"
          "--settings"
          (systemdLiteral settingsFile)
          "--state"
          "%S/agent-deck-slack-watchdog/state.json"
          "--systemctl"
          "${pkgs.systemd}/bin/systemctl"
        ];
        TimeoutStartSec = cfg.serviceTimeout;
        UMask = "0077";
        StateDirectory = "agent-deck-slack-watchdog";
        StateDirectoryMode = "0700";
        NoNewPrivileges = true;
        ProtectControlGroups = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        RestrictAddressFamilies = [ "AF_UNIX" ];
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
      };
    };

    systemd.user.timers.agent-deck-slack-watchdog = {
      Unit.Description = "Periodic Agent Deck Slack gateway qualification";
      Timer = {
        OnUnitInactiveSec = cfg.interval;
        Persistent = true;
        RandomizedDelaySec = cfg.randomizedDelay;
        AccuracySec = "1s";
        Unit = "agent-deck-slack-watchdog.service";
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
