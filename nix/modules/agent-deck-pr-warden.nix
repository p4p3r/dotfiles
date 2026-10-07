{ config
, lib
, pkgs
, ...
}:
let
  cfg = config.programs.agent-deck-pr-warden;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-pr-warden";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec"
      install -m 0400 \
        ${../../private_dot_local/bin/private_executable_agent-deck-pr-warden-controller} \
        "$out/libexec/agent-deck-pr-warden-controller.py"
      makeWrapper ${pkgs.python3}/bin/python3 \
        "$out/bin/agent-deck-pr-warden-controller" \
        --add-flags "$out/libexec/agent-deck-pr-warden-controller.py"
      chmod 0700 "$out/bin/agent-deck-pr-warden-controller"
      runHook postInstall
    '';
  };
  configPath = if cfg.runtimeConfig == null then "" else cfg.runtimeConfig;
  literalPath = lib.replaceStrings [ "%" ] [ "%%" ] configPath;
in
{
  options.programs.agent-deck-pr-warden = {
    enable = lib.mkEnableOption "the fake-only Agent Deck PR-warden controller";
    runtimeConfig = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Absolute owner-only PR-warden runtime JSON path outside the Nix store.";
    };
    package = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = runtime;
      description = "Owner-only PR-warden lifecycle controller.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "agent-deck-pr-warden requires Linux.";
      }
      {
        assertion =
          cfg.runtimeConfig != null
          && lib.hasPrefix "/" configPath
          && !(lib.hasPrefix "/nix/store/" configPath)
          && builtins.match ".*[\n\r].*" configPath == null;
        message = "agent-deck-pr-warden.runtimeConfig must be an absolute path outside the Nix store.";
      }
    ];

    home.packages = [ runtime ];

    systemd.user.services.agent-deck-pr-warden = {
      Unit = {
        Description = "Fake-only Agent Deck PR-warden lifecycle tick";
        ConditionPathExists = literalPath;
      };
      Service = {
        Type = "oneshot";
        ExecStartPre = lib.escapeShellArgs [
          "${pkgs.coreutils}/bin/install"
          "-m"
          "0700"
          "${runtime}/libexec/agent-deck-pr-warden-controller.py"
          "%t/agent-deck-pr-warden/controller.py"
        ];
        ExecStart = lib.escapeShellArgs [
          "${pkgs.python3}/bin/python3"
          "%t/agent-deck-pr-warden/controller.py"
          "--config"
          literalPath
          "tick"
        ];
        UMask = "0077";
        StateDirectory = [
          "agent-deck-pr-warden"
          "agent-deck-pr-warden-results"
          "agent-deck-pr-warden-handoffs"
        ];
        StateDirectoryMode = "0700";
        RuntimeDirectory = "agent-deck-pr-warden";
        RuntimeDirectoryMode = "0700";
        TimeoutStartSec = "20m";
        LimitCORE = 0;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ReadWritePaths = [
          "%S/agent-deck-pr-warden"
          "%S/agent-deck-pr-warden-results"
          "%S/agent-deck-pr-warden-handoffs"
          "%t/agent-deck-pr-warden"
        ];
        ProtectControlGroups = true;
        ProtectKernelTunables = true;
        RestrictAddressFamilies = [ "AF_UNIX" ];
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
      };
    };

    systemd.user.timers.agent-deck-pr-warden = {
      Unit.Description = "Periodic fake-only PR-warden control heartbeat";
      Timer = {
        OnUnitInactiveSec = "5m";
        Persistent = true;
        AccuracySec = "1m";
        Unit = "agent-deck-pr-warden.service";
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
