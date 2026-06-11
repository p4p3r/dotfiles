# Base PATH
# Note: fish’s PATH is a list of directories.
# System dirs are APPENDED (not prepended) so the Nix profiles stay ahead of
# /bin. Prepending them here demotes ~/.nix-profile/bin below /bin, which makes
# `tmux` resolve to /bin/tmux 3.4 instead of the Nix 3.6a — a 3.4 client cannot
# talk to the 3.6a server agent-deck runs.
fish_add_path -ga /usr/local/bin /usr/local/sbin /sbin /usr/sbin /bin /usr/bin

# Local bin directory takes priority
fish_add_path -gp $HOME/.local/bin

# Re-assert Nix profiles ahead of the system dirs
fish_add_path -gp $HOME/.nix-profile/bin /nix/var/nix/profiles/default/bin
