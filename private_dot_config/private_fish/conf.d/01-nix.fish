if test -e /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.fish
    source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.fish
end

# nix-darwin's set-environment is only sourced by zsh; always set SHELL correctly for fish
set -gx SHELL /run/current-system/sw/bin/fish