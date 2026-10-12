{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.agent-deck-janitor;
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "agent-deck-janitor-runtime";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/bin" "$out/libexec"
      install -m 0444 \
        ${../../private_dot_local/bin/executable_agent-deck-janitor} \
        "$out/libexec/agent-deck-janitor.py"
      makeWrapper ${pkgs.python3}/bin/python3 \
        "$out/bin/agent-deck-janitor" \
        --add-flags "$out/libexec/agent-deck-janitor.py"
      runHook postInstall
    '';
  };
  systemdLiteral = value: lib.replaceStrings [ "%" ] [ "%%" ] value;
  forbiddenRoots = [
    "/"
    "/bin"
    "/boot"
    "/dev"
    "/etc"
    "/home"
    "/lib"
    "/nix"
    "/opt"
    "/proc"
    "/root"
    "/run"
    "/sbin"
    "/srv"
    "/sys"
    "/usr"
    "/var"
    config.home.homeDirectory
  ];
  janitorArgs =
    [
      "${runtime}/bin/agent-deck-janitor"
      "--agent-deck"
      (systemdLiteral cfg.agentDeckExecutable)
      "--git"
      "${pkgs.git}/bin/git"
      "--state-dir"
      "%S/agent-deck-janitor/${cfg.stateNamespace}"
      "--report-root"
      "%S/agent-deck-janitor-reports/${cfg.stateNamespace}"
      "--session-retention-days"
      (toString cfg.sessionRetentionDays)
    ]
    ++ lib.optional cfg.emptyGroupSweep "--empty-groups"
    ++ lib.optionals cfg.apply [ "--apply" ]
    ++ lib.optionals (cfg.nixGenerationsDays != null) [
      "--nix-generations-days"
      (toString cfg.nixGenerationsDays)
    ]
    ++ lib.concatMap (name: [
      "--profile"
      name
    ]) cfg.profiles
    ++ lib.concatMap (name: [
      "--protect-group"
      name
    ]) cfg.protectedGroups
    ++ lib.concatMap (path: [
      "--repo"
      (systemdLiteral path)
    ]) cfg.repositoryRoots
    ++ lib.concatMap (rule: [
      "--artifact"
      (systemdLiteral "${rule.path}:${toString rule.olderThanDays}")
    ]) cfg.artifactRoots
    ++ lib.concatMap (rule: [
      "--expiring"
      (systemdLiteral "${rule.path}:${toString rule.olderThanDays}")
    ]) cfg.expiringPaths
    ++ lib.concatMap (pattern: [
      "--keep-pattern"
      pattern
    ]) cfg.keepPatterns;
in
{
  options.programs.agent-deck-janitor = {
    enable = lib.mkEnableOption "the deterministic Agent Deck and workspace janitor";

    agentDeckExecutable = lib.mkOption {
      type = lib.types.str;
      description = "Absolute path to the Agent Deck CLI.";
    };

    stateNamespace = lib.mkOption {
      type = lib.types.str;
      description = "Owner namespace for janitor state and reports.";
    };

    profiles = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Agent Deck profiles to sweep. Empty discovers every local profile.";
    };

    sessionRetentionDays = lib.mkOption {
      type = lib.types.ints.positive;
      default = 30;
      description = ''
        Days a dead session must have been inactive before it is purged. Only
        sessions with no live pane are eligible; archived are skipped and
        pinned are retained.
      '';
    };

    emptyGroupSweep = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Delete groups that hold no sessions and have no descendants.";
    };

    protectedGroups = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Group names or paths never deleted, however empty.";
    };

    repositoryRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Repositories whose administrative worktree entries are pruned, and
        whose drift is reported. Pruning cannot remove a worktree that still
        exists on disk.
      '';
    };

    artifactRoots = lib.mkOption {
      type = lib.types.listOf (
        lib.types.submodule {
          options = {
            path = lib.mkOption {
              type = lib.types.str;
              description = "Absolute scratch root whose immediate children expire.";
            };
            olderThanDays = lib.mkOption {
              type = lib.types.ints.positive;
              description = "Age in days at which a child of this root is removed.";
            };
          };
        }
      );
      default = [ ];
      description = ''
        Build and scratch roots swept by age. Only immediate children are
        considered, so one rule cannot walk a filesystem. Never point this at a
        source tree: the sweep is by age, not by tracked state.
      '';
    };

    expiringPaths = lib.mkOption {
      type = lib.types.listOf (
        lib.types.submodule {
          options = {
            path = lib.mkOption {
              type = lib.types.str;
              description = "Absolute path removed in full once it is old enough.";
            };
            olderThanDays = lib.mkOption {
              type = lib.types.ints.positive;
              description = "Age in days at which this exact path is removed.";
            };
          };
        }
      );
      default = [ ];
      description = ''
        Paths that are themselves the candidate, rather than roots whose
        children expire. A single large build directory is removed as a whole,
        and naming it explicitly means no pattern can expand to something
        unintended.
      '';
    };

    keepPatterns = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Regular expressions; a matching entry name is never removed.";
    };

    nixGenerationsDays = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      description = "Delete Nix generations older than this. Null skips the task.";
    };

    apply = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Perform deletions. False runs every task as a preview and writes the
        same report, which is the only safe way to learn what a new rule would
        have done on a live box.
      '';
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "daily";
      description = "systemd OnCalendar expression for the janitor timer.";
    };

    randomizedDelay = lib.mkOption {
      type = lib.types.str;
      default = "30m";
      description = "Bounded randomized delay applied to the timer.";
    };

    armTimer = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Install the timer into timers.target. False installs the unit without
        arming it, so a box can carry a reviewed janitor before its first
        scheduled run is authorized.
      '';
    };

    serviceTimeout = lib.mkOption {
      type = lib.types.str;
      default = "45min";
      description = "Systemd bound for one complete janitor run.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.isLinux;
        message = "programs.agent-deck-janitor is supported only on Linux.";
      }
      {
        assertion = builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" cfg.stateNamespace != null;
        message = "programs.agent-deck-janitor.stateNamespace is invalid.";
      }
      {
        assertion = lib.hasPrefix "/" cfg.agentDeckExecutable;
        message = "programs.agent-deck-janitor.agentDeckExecutable must be absolute.";
      }
      {
        assertion = lib.all (path: lib.hasPrefix "/" path) cfg.repositoryRoots;
        message = "programs.agent-deck-janitor.repositoryRoots must be absolute.";
      }
      {
        # The runtime refuses these too. Failing here as well means a typo is
        # caught when the configuration is built rather than on the first live
        # run against a box.
        assertion = lib.all (
          rule: lib.hasPrefix "/" rule.path && !(builtins.elem rule.path forbiddenRoots)
        ) (cfg.artifactRoots ++ cfg.expiringPaths);
        message = "programs.agent-deck-janitor paths must be absolute and never a system root.";
      }
    ];

    home.packages = [ runtime ];

    systemd.user.services.agent-deck-janitor = {
      Unit = {
        Description = "Deterministic Agent Deck and workspace janitor";
        ConditionFileIsExecutable = [ (systemdLiteral cfg.agentDeckExecutable) ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = lib.escapeShellArgs janitorArgs;
        TimeoutStartSec = cfg.serviceTimeout;
        UMask = "0077";
        StateDirectory = [
          "agent-deck-janitor"
          "agent-deck-janitor-reports"
        ];
        StateDirectoryMode = "0700";
        NoNewPrivileges = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
        # ProtectSystem is deliberately absent: this unit exists to delete
        # files outside its own state directory, which is exactly what a strict
        # filesystem namespace would prevent.
        Environment = [
          (systemdLiteral "PATH=${config.home.homeDirectory}/.local/bin:${
            lib.makeBinPath [
              pkgs.coreutils
              pkgs.git
              pkgs.nix
              pkgs.tmux
              pkgs.bash
            ]
          }")
        ];
      };
    };

    systemd.user.timers.agent-deck-janitor = {
      Unit.Description = "Scheduled deterministic janitor trigger";
      Timer = {
        OnCalendar = cfg.schedule;
        Persistent = true;
        RandomizedDelaySec = cfg.randomizedDelay;
        AccuracySec = "1m";
        Unit = "agent-deck-janitor.service";
      };
      Install.WantedBy = lib.optional cfg.armTimer "timers.target";
    };
  };
}
