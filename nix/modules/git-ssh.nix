{ config, pkgs, lib, ... }:
{
  # Set SSH_AUTH_SOCK to use 1Password SSH agent
  home.sessionVariables = lib.optionalAttrs pkgs.stdenv.isDarwin {
    SSH_AUTH_SOCK = "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock";
  };

  # ---------------------------------------------------------------------------
  # Git (home-manager 25.11 layout)
  #   - programs.git.extraConfig → programs.git.settings
  #   - programs.git.aliases     → programs.git.settings.alias
  #   - programs.git.delta       → top-level programs.delta
  # ---------------------------------------------------------------------------
  programs.git = {
    enable = true;

    settings = {
      init.defaultBranch = "main";

      # Pull behavior
      pull.rebase = true;
      rebase.autoStash = true;

      # Better diffs
      diff = {
        algorithm = "histogram";
        colorMoved = "default";
      };

      # Better merge conflict resolution
      merge.conflictstyle = "diff3";

      # Push behavior
      push.default = "simple";
      push.autoSetupRemote = true;

      # Credential handling (1Password)
      credential.helper = if pkgs.stdenv.isDarwin then "osxkeychain" else "";

      # Performance
      core.preloadindex = true;
      core.fscache = true;

      # Aliases (was programs.git.aliases)
      alias = {
        st = "status -sb";
        co = "checkout";
        br = "branch";
        ci = "commit";
        ca = "commit --amend";
        df = "diff";
        dc = "diff --cached";
        lg = "log --graph --pretty=format:'%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset' --abbrev-commit";
        ls = "log --pretty=format:'%C(yellow)%h %Cred%ad %Cblue%an%Cgreen%d %Creset%s' --date=short";
        undo = "reset HEAD~1 --mixed";
        amend = "commit -a --amend --no-edit";
        unstage = "reset HEAD --";
      };
    };

    # Git LFS
    lfs.enable = true;
  };

  # Delta is now top-level. Explicit enableGitIntegration silences the
  # auto-enablement deprecation warning.
  programs.delta = {
    enable = true;
    enableGitIntegration = true;
    options = {
      navigate = true;
      light = false;
      side-by-side = true;
      line-numbers = true;
    };
  };

  # ---------------------------------------------------------------------------
  # SSH (home-manager 25.11 layout)
  #   programs.ssh.matchBlocks is a deprecated alias for programs.ssh.settings.
  #   Blocks are now freeform attrsets keyed by Host/Match pattern, holding raw
  #   OpenSSH directive names (HostName, ServerAliveInterval, ForwardAgent, …) —
  #   no camelCase options and no extraOptions escape hatch. Values: bool →
  #   yes/no, int → number, string verbatim. DAG ordering via lib.hm.dag still
  #   applies. enableDefaultConfig = false stops HM injecting its own "*".
  # ---------------------------------------------------------------------------
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;

    # OrbStack + sbx drop-in configs — Include order matters (first match wins)
    includes =
      (lib.optionals pkgs.stdenv.isDarwin [ "~/.orbstack/ssh/config" ])
      ++ [ "~/.ssh/config.d/*" ];

    settings = {
      # Sandbox EC2 boxes (172.19.x), reached over the Tailscale subnet route.
      # agent-deck connects to these BY IP with its own mux socket
      # (/tmp/agent-deck-ssh/%r@%h:%p). When the Tailscale route flaps, a mux
      # master's TCP dies but the master process lingers as a zombie — every new
      # session-attach then can't reuse it, prints "disabling multiplexing", and
      # pays a full cold handshake (~4s vs ~0.6s warm). Tight keepalive makes a
      # dead master self-exit in ~45s (vs 180s under the "*" defaults) so the
      # socket frees and the next connect rebuilds a healthy, reusable master;
      # ConnectTimeout fails a genuinely-unreachable box fast instead of hanging.
      # Ordered before "*" so these win the first-match on ServerAlive*.
      "172.19.*" = lib.hm.dag.entryBefore [ "*" ] {
        ServerAliveInterval = 15;
        ServerAliveCountMax = 3;
        ConnectTimeout = 5;
      };

      # Home Assistant host
      "antioche-ha.local" = {
        HostName = "antioche-ha.local";
        User = "hassio";
        ForwardAgent = true;
      };

      # SSH keys managed by 1Password SSH agent — no IdentityFile needed.
      "github.com" = { };
      "gitlab.com" = { };

      # Wildcard: defaults that used to live at programs.ssh.* top level.
      "*" = {
        AddKeysToAgent = "yes";
        ControlMaster = "auto";
        ControlPath = "~/.ssh/control-%C";
        ControlPersist = "10m";
        ServerAliveInterval = 60;
        ServerAliveCountMax = 3;
        PubkeyAcceptedKeyTypes = "ssh-ed25519,ssh-rsa";
      } // lib.optionalAttrs pkgs.stdenv.isDarwin {
        IdentityAgent = ''"~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"'';
      };
    };
  };
}
