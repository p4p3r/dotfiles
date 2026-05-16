starship init fish | source

set fish_greeting
set -gx ZELLIJ_CONFIG_DIR $HOME/.config/zellij

# Added by OrbStack: command-line tools and integration
# This won't be added again if you remove it.
source ~/.orbstack/shell/init2.fish 2>/dev/null || :

# User-managed bins must precede /opt/homebrew/bin so upstream-installer
# binaries (pup, claude, agent-deck, etc. under ~/.local/bin) win over any
# stale brew copies left behind during the brew→nix migration.
# --move ensures these entries get repositioned to the front even if already present.
fish_add_path --move --prepend $HOME/.local/bin
fish_add_path --move --prepend $HOME/.npm-global/bin
fish_add_path --move --prepend $HOME/.opencode/bin
