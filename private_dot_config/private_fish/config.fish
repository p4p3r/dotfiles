starship init fish | source

set fish_greeting
set -gx ZELLIJ_CONFIG_DIR $HOME/.config/zellij

# Added by OrbStack: command-line tools and integration
# This won't be added again if you remove it.
source ~/.orbstack/shell/init2.fish 2>/dev/null || :

# opencode (installed under $HOME by the upstream installer; path string was
# baked from macOS originally — use $HOME so it works on Linux too)
fish_add_path $HOME/.opencode/bin
