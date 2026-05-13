function nix_switch --description "Build and activate the darwin system configuration"
    set -l flake ~/.config/nix
    # Override nix-private to the real path of the working clone. We use the
    # real path (not the ~/.config/private symlink) because nix's `path:` flake
    # input type errors during lock-file writes when given a symlink.
    set -l private ~/Code/p4p3r/dotfiles-private
    echo "Switching to $flake ..."
    sudo env USER=$USER darwin-rebuild switch --flake $flake --override-input nix-private path:$private $argv
    or return $status

    # On nix-darwin 25.05, the system-level `switch` no longer reliably runs
    # the user-level home-manager activation in every case (the deprecated
    # `activate-user` path skips). Re-run the user activation explicitly so
    # ~/.local/bin/sg-devbox, ~/.config/fish/conf.d/*, etc. always get linked
    # against the latest generation.
    set -l hm (find /run/current-system -maxdepth 1 -name 'activate-paper' -print -quit ^/dev/null)
    if test -z "$hm"
        # Fallback: walk the activation-<user> script that current-system points
        # to; it execs the home-manager generation's activate.
        set hm /run/current-system/activate
    end
    # Run the home-manager generation's activate directly. It's idempotent.
    set -l hm_gen (sudo grep -hoE '/nix/store/[a-z0-9]+-home-manager-generation' /run/current-system/activate | head -1)
    if test -n "$hm_gen"; and test -x "$hm_gen/activate"
        echo "Running home-manager activation ($hm_gen)…"
        "$hm_gen/activate"
    end
end
