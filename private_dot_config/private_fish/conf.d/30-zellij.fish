# Auto-launch Zellij in Ghostty — runs after PATH setup (nix, brew) but
# before heavy conf.d (languages, creds) so parent shell stays lightweight.

if status is-interactive; and test "$TERM" = xterm-ghostty; and not set -q ZELLIJ; and not set -q CONDUCTOR_WORKSPACE_NAME; and not set -q SKIP_MUX
    # Defensively drop any tmux-mode leak from a parent agent-deck shell.
    set -e USE_TMUX
    set -gx ZELLIJ_CONFIG_DIR $HOME/.config/zellij

    # Honor explicit target dir set by ghostty-here (--working-directory unreliable in 1.2)
    if set -q GHOSTTY_TARGET_DIR
        cd $GHOSTTY_TARGET_DIR
        set -e GHOSTTY_TARGET_DIR
    end

    set -l _zj_name (fish_get_session_name)
    if set -q SIMPLE
        set _zj_name simple
    else if set -q ZELLIJ_SESSION_NAME
        set _zj_name $ZELLIJ_SESSION_NAME
    end

    # Abbreviate if too long for Unix socket path limit (~104 chars on macOS)
    if test (string length -- $_zj_name) -gt 40
        set _zj_name (_shorten_name $_zj_name)
    end

    # Set Ghostty window title to session name
    printf '\e]0;%s\a' $_zj_name

    # Generic sessions (main, simple, config) always start fresh.
    # Project sessions use attach --create to allow resurrection.
    switch $_zj_name
        case main simple config
            zellij kill-session $_zj_name &>/dev/null
            zellij delete-session $_zj_name &>/dev/null
            exec zellij -s $_zj_name
        case '*'
            exec zellij attach $_zj_name --create
    end
end
