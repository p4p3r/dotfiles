function nix_build --description "Build the system configuration (darwin or home-manager) without activating"
    set -l flake ~/.config/nix
    set -l private ~/Code/p4p3r/dotfiles-private
    set -l override --override-input nix-private path:$private

    if test (uname) = Darwin
        set -l host (hostname -s)
        echo "Building $flake#darwinConfigurations.$host.system ..."
        nix build "$flake#darwinConfigurations.$host.system" $override --impure --no-link $argv
    else
        set -l arch (uname -m)
        set -l suffix ""
        switch $arch
            case x86_64
                set suffix linux-x86_64
            case aarch64 arm64
                set suffix linux-aarch64
            case '*'
                echo "Unsupported Linux arch: $arch" >&2
                return 1
        end
        set -l target "$flake#homeConfigurations.$USER@$suffix.activationPackage"
        echo "Building $target ..."
        NIX_CONFIG='experimental-features = nix-command flakes' \
            nix build $target $override --impure --no-link $argv
    end
end
