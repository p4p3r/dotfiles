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
  #   programs.ssh.{addKeysToAgent,controlMaster,controlPath,controlPersist,
  #     serverAliveInterval,serverAliveCountMax} are deprecated at top level.
  #   Move them into programs.ssh.matchBlocks."*". enableDefaultConfig = false
  #   stops HM from injecting its own defaults that would conflict.
  # ---------------------------------------------------------------------------
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;

    # OrbStack SSH integration — MUST be first (before any Host blocks)
    includes = lib.optionals pkgs.stdenv.isDarwin [ "~/.orbstack/ssh/config" ];

    matchBlocks = {
      # Home Assistant host
      "antioche-ha.local" = {
        hostname = "antioche-ha.local";
        user = "hassio";
        forwardAgent = true;
      };

      "github.com" = {
        # SSH keys managed by 1Password SSH agent
        # No identityFile needed - 1Password provides keys
      };

      "gitlab.com" = {
      };

      # Wildcard: defaults that used to live at programs.ssh.* top level, plus
      # the existing extraOptions.
      "*" = {
        addKeysToAgent = "yes";
        controlMaster = "auto";
        controlPath = "~/.ssh/control-%C";
        controlPersist = "10m";
        serverAliveInterval = 60;
        serverAliveCountMax = 3;

        extraOptions = {
          PubkeyAcceptedKeyTypes = "ssh-ed25519,ssh-rsa";
        } // lib.optionalAttrs pkgs.stdenv.isDarwin {
          IdentityAgent = ''"~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"'';
        };
      };
    };
  };
}
