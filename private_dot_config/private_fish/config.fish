# set -x PATH /opt/homebrew/bin $PATH

starship init fish | source

# Unset the default fish greeting text which messes up Zellij
set fish_greeting

# Check if we're in an interactive shell
if status is-interactive
    # At this point, specify the Zellij config dir, so we can launch it manually if we want to
    export ZELLIJ_CONFIG_DIR=$HOME/.config/zellij

    # Check if our Terminal emulator is Ghostty
    if [ "$TERM" = "xterm-ghostty" ]
        # Check if already in zellij (prevent nesting)
        if not set -q ZELLIJ
            # Determine session name
            if set -q SIMPLE
                set -l _zj_name simple
            else if set -q ZELLIJ_SESSION_NAME
                set -l _zj_name $ZELLIJ_SESSION_NAME
            else
                set -l _zj_name (fish_get_session_name)
            end
            # Delete dead (EXITED) sessions to avoid resurrection hangs
            zellij delete-session $_zj_name 2>/dev/null
            exec zellij attach $_zj_name --create
        end
    end
end

# Added by OrbStack: command-line tools and integration
# This won't be added again if you remove it.
source ~/.orbstack/shell/init2.fish 2>/dev/null || :
