function nix_build --description "Build the system configuration (darwin or home-manager) without activating"
    set -l flake ~/.config/nix
    set -l private ~/Code/p4p3r/dotfiles-private
    set -l override --override-input nix-private path:$private

    if test (uname) = Darwin
        set -l host (hostname -s)
        echo "Building $flake#darwinConfigurations.$host.system ..."
        nix build "$flake#darwinConfigurations.$host.system" $override --impure --no-link $argv
    else
        set -l target "$flake#homeConfigurations.$USER@linux.activationPackage"
        echo "Building $target ..."
        nix build $target $override --impure --no-link $argv
    end
end
