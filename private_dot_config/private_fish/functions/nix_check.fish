function nix_check --description "Run nix flake check on the system flake"
    set -l flake ~/.config/nix
    set -l private ~/Code/p4p3r/dotfiles-private
    echo "Checking $flake ..."
    nix flake check $flake --override-input nix-private path:$private $argv
end
