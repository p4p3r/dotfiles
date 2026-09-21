function nix_update --description "Update flake inputs, rebuild, switch, push the lock; --brew also upgrades Homebrew"
    argparse brew -- $argv; or return 1

    set -l flake ~/.config/nix
    set -l repo ~/Code/p4p3r/dotfiles

    # 1. Bump flake.lock — all inputs, or only the ones named as args.
    if test (count $argv) -eq 0
        echo "Updating all flake inputs ..."
        nix flake update --flake $flake; or return 1
    else
        for input in $argv
            echo "Updating $input ..."
            nix flake update $input --flake $flake; or return 1
        end
    end

    # 2. Build / switch / push only when the lock actually changed.
    if git -C $repo diff --quiet -- nix/flake.lock
        echo "flake.lock unchanged; skipping build/switch/push."
    else
        echo "Building with updated inputs ..."
        if not nix_build
            echo "nix_build failed — flake.lock left modified, NOT switching or pushing." >&2
            return 1
        end
        if not nix_switch
            echo "nix_switch failed — NOT pushing flake.lock." >&2
            return 1
        end
        set -l msg "chore(nix): flake update"
        if test (count $argv) -gt 0
            set msg "$msg $argv"
        end
        echo "Committing and pushing flake.lock ..."
        git -C $repo add nix/flake.lock
        git -C $repo commit -m "$msg"; or return 1
        if not git -C $repo pull --rebase origin main
            echo "rebase failed — resolve, then run: git -C $repo push origin main" >&2
            return 1
        end
        git -C $repo push origin main; or return 1
    end

    # 3. Optional Homebrew upgrade. Kept behind a flag because it is a separate
    # surface: onActivation.upgrade=false means a nix switch never touches brew.
    if set -q _flag_brew
        echo "Updating Homebrew ..."
        brew update; and brew upgrade; and brew upgrade --cask
    end
end
