function nix_update --description "Update flake inputs (all or specific)"
    set -l flake ~/.config/nix
    if test (count $argv) -eq 0
        echo "Updating all flake inputs ..."
        nix flake update --flake $flake
    else
        for input in $argv
            echo "Updating $input ..."
            nix flake update $input --flake $flake
        end
    end
end
