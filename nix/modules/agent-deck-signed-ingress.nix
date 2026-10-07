{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-signed-ingress;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-signed-ingress";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec"
      install -m 0444 ${../../private_dot_local/bin/executable_agent-deck-signed-ingress} \
        "$out/libexec/agent-deck-signed-ingress.py"
      makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/agent-deck-signed-ingress" \
        --add-flags "$out/libexec/agent-deck-signed-ingress.py"
      runHook postInstall
    '';
  };
  configPath = if cfg.runtimeConfig == null then "" else cfg.runtimeConfig;
  literalPath = lib.replaceStrings [ "%" ] [ "%%" ] configPath;
in
{
  options.programs.agent-deck-signed-ingress = {
    enable = lib.mkEnableOption "the local signed webhook admission ledger";
    runtimeConfig = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Absolute owner-only runtime JSON path outside the Nix store; contains file references, never secret values.";
    };
    package = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = runtime;
      description = "Standard-library signed ingress and Unix-socket control executable.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "agent-deck-signed-ingress requires Linux.";
      }
      {
        assertion =
          cfg.runtimeConfig != null
          && lib.hasPrefix "/" configPath
          && !(lib.hasPrefix "/nix/store/" configPath)
          && builtins.match ".*[\n\r].*" configPath == null;
        message = "agent-deck-signed-ingress.runtimeConfig must be an absolute runtime path outside the Nix store.";
      }
    ];
    home.packages = [ runtime ];
    systemd.user.services.agent-deck-signed-ingress = {
      Unit = {
        Description = "Signed loopback admission and owner-only event ledger";
        ConditionPathExists = literalPath;
        StartLimitIntervalSec = 300;
        StartLimitBurst = 3;
      };
      Service = {
        Type = "simple";
        ExecStart = lib.escapeShellArgs [
          "${runtime}/bin/agent-deck-signed-ingress"
          "--config"
          literalPath
          "serve"
        ];
        UMask = "0077";
        StateDirectory = "agent-deck-signed-ingress";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "agent-deck-signed-ingress";
        RuntimeDirectoryMode = "0700";
        Restart = "on-failure";
        RestartSec = 5;
        TimeoutStartSec = 10;
        TimeoutStopSec = 10;
        LimitCORE = 0;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        ReadWritePaths = [
          "%S/agent-deck-signed-ingress"
          "%t/agent-deck-signed-ingress"
        ];
        ProtectControlGroups = true;
        ProtectKernelTunables = true;
        RestrictAddressFamilies = [
          "AF_UNIX"
          "AF_INET"
        ];
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
      };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
