function nix_build --description "Build the darwin system configuration"
    set -l flake ~/.config/nix
    set -l private ~/Code/p4p3r/dotfiles-private
    set -l host (hostname -s)
    echo "Building $flake#darwinConfigurations.$host.system ..."
    nix build "$flake#darwinConfigurations.$host.system" --override-input nix-private path:$private --no-link $argv
end
