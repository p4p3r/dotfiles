# Set EDITOR (if vim exists) and VISUAL
if type -q vim
    set -x EDITOR (which vim)
end
set -x VISUAL $EDITOR
