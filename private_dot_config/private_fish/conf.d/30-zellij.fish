# Auto-launch Zellij in Ghostty — runs after PATH setup (nix, brew) but
# before heavy conf.d (languages, creds) so parent shell stays lightweight.

if status is-interactive; and test "$TERM" = xterm-ghostty; and not set -q ZELLIJ
    set -gx ZELLIJ_CONFIG_DIR $HOME/.config/zellij

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

    zellij delete-session $_zj_name &>/dev/null
    zellij kill-session $_zj_name &>/dev/null
    exec zellij -s $_zj_name
end
