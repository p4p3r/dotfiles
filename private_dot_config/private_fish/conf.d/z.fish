# Recompute Z_DATA every shell startup against the current $HOME. Earlier this
# used `set -U`, which persists into ~/.config/fish/fish_variables — when
# fish_variables is chezmoi-managed and synced across machines, a macOS-set
# value like /Users/paper/.local/share/z follows you to a Linux box and breaks.
# Erase any stale universal value, then use `set -gx` for the current session.
set -eU Z_DATA_DIR 2>/dev/null
set -eU Z_DATA     2>/dev/null
if test -z "$XDG_DATA_HOME"
    set -gx Z_DATA_DIR "$HOME/.local/share/z"
else
    set -gx Z_DATA_DIR "$XDG_DATA_HOME/z"
end
set -gx Z_DATA "$Z_DATA_DIR/data"

if test ! -e "$Z_DATA"
    if test ! -e "$Z_DATA_DIR"
        mkdir -p -m 700 "$Z_DATA_DIR"
    end
    touch "$Z_DATA"
end

if test -z "$Z_CMD"
    set -U Z_CMD z
end

set -U ZO_CMD "$Z_CMD"o

if test ! -z $Z_CMD
    function $Z_CMD -d "jump around"
        __z $argv
    end
end

if test ! -z $ZO_CMD
    function $ZO_CMD -d "open target dir"
        __z -d $argv
    end
end

# Z_EXCLUDE embeds $HOME, so a universal value carried across machines points
# at the wrong dir. Recompute it per-session like Z_DATA above.
set -eU Z_EXCLUDE 2>/dev/null
set -gx Z_EXCLUDE "^$HOME\$"

# Setup completions once first
__z_complete

function __z_on_variable_pwd --on-variable PWD
    __z_add
end

function __z_uninstall --on-event z_uninstall
    functions -e __z_on_variable_pwd
    functions -e $Z_CMD
    functions -e $ZO_CMD

    if test ! -z "$Z_DATA"
        printf "To completely erase z's data, remove:\n" >/dev/stderr
        printf "%s\n" "$Z_DATA" >/dev/stderr
    end

    set -e Z_CMD
    set -e ZO_CMD
    set -e Z_DATA
    set -e Z_EXCLUDE
end
