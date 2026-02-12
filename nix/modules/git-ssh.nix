{ config, pkgs, lib, ... }:
{
  # Set SSH_AUTH_SOCK to use 1Password SSH agent
  home.sessionVariables = {
    SSH_AUTH_SOCK = "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock";
  };

  # Git configuration
  programs.git = {
    enable = true;

    # Basic configuration
    extraConfig = {
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
      credential.helper = "osxkeychain";

      # Performance
      core.preloadindex = true;
      core.fscache = true;
    };

    # Git aliases
    aliases = {
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

    # Delta for better diffs (if installed)
    delta = {
      enable = true;
      options = {
        navigate = true;
        light = false;
        side-by-side = true;
        line-numbers = true;
      };
    };

    # Git LFS
    lfs.enable = true;
  };

  # SSH configuration
  programs.ssh = {
    enable = true;

    # OrbStack SSH integration - MUST be first (before any Host blocks)
    includes = [ "~/.orbstack/ssh/config" ];

    # Add keys to SSH agent
    addKeysToAgent = "yes";

    # Connection multiplexing for faster connections
    controlMaster = "auto";
    controlPath = "~/.ssh/control-%C";
    controlPersist = "10m";

    # Server alive settings
    serverAliveInterval = 60;
    serverAliveCountMax = 3;

    # Host-specific configurations
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

      # Wildcard settings for all hosts
      "*" = {
        identityAgent = ''"~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"'';
        extraOptions = {
          PubkeyAcceptedKeyTypes = "ssh-ed25519,ssh-rsa";
        };
      };
    };
  };
}
