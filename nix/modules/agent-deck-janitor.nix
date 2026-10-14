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
      "--stop-idle-days"
      (toString cfg.stopIdleDays)
      "--stopped-retention-days"
      (toString cfg.stoppedRetentionDays)
      "--archived-retention-days"
      (toString cfg.archivedRetentionDays)
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
    ++ map (name: "--protect-group=${name}") cfg.protectedGroups
    ++ map (title: "--protect-session-title=${title}") cfg.protectedSessionTitles
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
    # A regular expression may legitimately begin with "-", which argparse
    # would read as an option: the first armed run died on --keep-pattern
    # -1000$ before doing anything. The --opt=value form has no such ambiguity.
    ++ map (pattern: "--keep-pattern=${pattern}") cfg.keepPatterns
    ++ lib.optionals (cfg.reclaimRepositoryRoots != [ ]) [
      "--gh"
      (systemdLiteral cfg.ghExecutable)
      "--reclaim-grace-days"
      (toString cfg.reclaimGraceDays)
    ]
    ++ lib.concatMap (path: [
      "--reclaim-repo"
      (systemdLiteral path)
    ]) cfg.reclaimRepositoryRoots
    ++ lib.optionals (cfg.tmuxSocketRoots != [ ]) [
      "--tmux"
      "${pkgs.tmux}/bin/tmux"
      "--tmux-idle-days"
      (toString cfg.tmuxIdleDays)
    ]
    ++ lib.concatMap (path: [
      "--tmux-socket-root"
      (systemdLiteral path)
    ]) cfg.tmuxSocketRoots
    # A socket name may begin with "-", for the same reason a keep pattern may.
    ++ map (name: "--protect-tmux-socket=${name}") cfg.protectedTmuxSockets;
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

    stopIdleDays = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 0;
      description = ''
        Stop a session whose agent has sat at a prompt this long. `session
        cleanup` purges only rows with no live pane, and a waiting row has one,
        so without this no retention window can ever reach it: box 2 carried 62
        such rows aged 7 to 34 days, each holding a live process.

        Stopping keeps the row, its transcript and its worktree, and makes it
        an ordinary dead row that stoppedRetentionDays then reclaims on a later
        run. It does destroy in-memory context and anything unsent in the
        composer, which is why this window should be the longest one here, and
        why a running session, a protected title and a pane someone is watching
        are all left alone. Zero never stops anything.
      '';
    };

    stoppedRetentionDays = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 0;
      description = ''
        Shorter window for rows an agent already finished with. A conductor
        fleet creates stopped rows by the dozen for a single piece of work and
        never returns to them, so they need not wait as long as a row that
        merely went quiet. Zero uses sessionRetentionDays, and a value above it
        is rejected: a stopped row is a subset of an idle one, so a longer
        window would silently never apply.
      '';
    };

    archivedRetentionDays = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 0;
      description = ''
        Window for archived rows. `session cleanup` never offers one unless
        asked, so nothing has ever reclaimed them: they are invisible in the
        TUI and permanent in the registry. Zero keeps that behaviour; a value
        bounds it.
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

    protectedSessionTitles = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Session titles never purged, however long they have been dead. The CLI
        retains pinned sessions, but a pin has no command to set it, so
        exemption is applied here: the CLI still decides what is dead and idle,
        and these titles are removed from its candidate list.
      '';
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

    reclaimRepositoryRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Repositories whose worktrees are reclaimed once their pull request has
        merged. A worktree is removed only when its branch has a MERGED pull
        request, its HEAD still equals that pull request's head, it holds no
        uncommitted changes, and no session is using it.

        The pull request is the load-bearing evidence and local git cannot
        replace it: squash-merge rewrites the commits, so a fully merged branch
        still reports commits ahead of the trunk and `git cherry` still reports
        unmerged patches.
      '';
    };

    reclaimGraceDays = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 0;
      description = ''
        Keep a worktree for this long after its pull request merged, so a
        follow-up does not lose its tree moments after the merge lands.
      '';
    };

    ghExecutable = lib.mkOption {
      type = lib.types.str;
      default = "gh";
      description = "GitHub CLI used for read-only pull request state.";
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

    tmuxSocketRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Directories holding tmux socket files, typically /tmp/tmux-<uid>. A
        session there is killed only when no Agent Deck row claims it, no
        client is attached and it has been idle past tmuxIdleDays; a socket
        file is deleted only when its server does not answer. Empty skips the
        task.
      '';
    };

    tmuxIdleDays = lib.mkOption {
      type = lib.types.ints.positive;
      default = 7;
      description = "Idle window before an unclaimed tmux session may be killed.";
    };

    protectedTmuxSockets = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Socket files that are never deleted, whatever their server reports.
        The socket the conductor's panes live on belongs here, so a transient
        probe failure can never unlink it. Sessions on a protected socket are
        still judged by the ordinary rules: that socket is also where test
        harnesses leave their litter.
      '';
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
              pkgs.gh
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
