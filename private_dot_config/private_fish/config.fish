starship init fish | source

set fish_greeting
set -gx ZELLIJ_CONFIG_DIR $HOME/.config/zellij

# Added by OrbStack: command-line tools and integration
# This won't be added again if you remove it.
source ~/.orbstack/shell/init2.fish 2>/dev/null || :

# opencode
fish_add_path /Users/paper/.opencode/bin
