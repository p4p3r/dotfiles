if test -e /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.fish
    source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.fish
end

# nix-darwin sets SHELL via set-environment; on Linux, resolve dynamically
if test -e /run/current-system/sw/bin/fish
    set -gx SHELL /run/current-system/sw/bin/fish
else if command -q fish
    set -gx SHELL (command -s fish)
end