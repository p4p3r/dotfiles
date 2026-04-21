function nix_switch --description "Build and activate the darwin system configuration"
    set -l flake ~/.config/nix
    # Override nix-private to the real path of the working clone. We use the
    # real path (not the ~/.config/private symlink) because nix's `path:` flake
    # input type errors during lock-file writes when given a symlink.
    set -l private ~/Code/p4p3r/dotfiles-private
    echo "Switching to $flake ..."
    sudo env USER=$USER darwin-rebuild switch --flake $flake --override-input nix-private path:$private $argv
end
