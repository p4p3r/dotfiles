function nix_switch --description "Build and activate the darwin system configuration"
    set -l flake ~/.config/nix
    # Override nix-private to the real path of the working clone. We use the
    # real path (not the ~/.config/private symlink) because nix's `path:` flake
    # input type errors during lock-file writes when given a symlink.
    set -l private ~/Code/p4p3r/dotfiles-private
    echo "Switching to $flake ..."
    sudo env USER=$USER darwin-rebuild switch --flake $flake --override-input nix-private path:$private $argv
    or return $status

    # nix-darwin's switch can leave /run/current-system pointing at an older
    # generation while /nix/var/nix/profiles/system is already bumped to the
    # newly built one. Re-running home-manager activation from /run/current-system
    # would then re-activate the OLD gen and silently revert home.file changes.
    # Two hops: system's `activate` references a per-user `activation-<user>`
    # script which in turn exec's the home-manager generation's `activate`.
    set -l latest /nix/var/nix/profiles/system
    set -l act_user (sudo grep -hoE '/nix/store/[a-z0-9]+-activation-[a-z_-]+' $latest/activate | head -1)
    if test -n "$act_user"; and test -f "$act_user"
        set -l hm_gen (sudo grep -hoE '/nix/store/[a-z0-9]+-home-manager-generation' $act_user | head -1)
        if test -n "$hm_gen"; and test -x "$hm_gen/activate"
            echo "Running home-manager activation ($hm_gen)…"
            "$hm_gen/activate"
        end
    end
end
