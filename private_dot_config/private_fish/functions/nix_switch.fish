function nix_switch --description "Build and activate the system configuration (darwin or home-manager)"
    set -l flake ~/.config/nix
    # Override nix-private to the real path of the working clone. We use the
    # real path (not the ~/.config/private symlink) because nix's `path:` flake
    # input type errors during lock-file writes when given a symlink.
    set -l private ~/Code/p4p3r/dotfiles-private
    set -l override --override-input nix-private path:$private

    if test (uname) = Darwin
        echo "Switching to $flake (darwin) ..."
        set -l rebuild_log (mktemp)
        sudo env USER=$USER darwin-rebuild switch --flake $flake $override --impure $argv 2>&1 | tee $rebuild_log
        set -l rebuild_status $pipestatus[1]

        # Finish HM activation even when Homebrew/mas exits nonzero for a benign
        # already-installed App Store app. Surface real rebuild failures later.
        if test $rebuild_status -ne 0
            set -l sudo_errors (grep -iE 'sudo: .*password|sudo: a terminal is required|sudo: .*authentication' $rebuild_log)
            set -l mas_errors (grep -iE 'mas installation failed|Unable to install .* app\.' $rebuild_log)
            set -l real_errors (grep -iE 'error' $rebuild_log | grep -viE 'mas installation failed|Unable to install .* app\.')
            if test (count $sudo_errors) -gt 0
                echo "ERROR: darwin-rebuild could not run because sudo authentication failed. Not running HM activation from a stale system generation." >&2
                rm -f $rebuild_log
                return $rebuild_status
            else if test (count $mas_errors) -gt 0; and test (count $real_errors) -eq 0
                echo "WARN: darwin-rebuild exited $rebuild_status but only reported a benign mas install failure; treating as success." >&2
                set rebuild_status 0
            else
                echo "WARN: darwin-rebuild switch exited $rebuild_status with real errors. Continuing to HM activation; will report at end." >&2
                printf '  %s\n' $real_errors >&2
            end
        end
        rm -f $rebuild_log

        # Capture the home-manager profile generation count BEFORE re-running
        # HM activate. We verify AFTER that the count grew — that proves the
        # user-level activation actually fired and the ~/.local/bin/foo
        # symlinks point at the new generation. Without this check, a silent
        # failure leaves stale user-level state (saw this happen on 2026-05-16,
        # where the system gen bumped to 78 but the HM profile stayed at 42
        # because nix-darwin's `launchctl asuser` step apparently no-op'd).
        set -l hm_before (count /Users/$USER/.local/state/nix/profiles/home-manager-*-link 2>/dev/null)

        # nix-darwin's switch can leave /run/current-system pointing at an older
        # generation while /nix/var/nix/profiles/system is already bumped to the
        # newly built one. Re-running home-manager activation from /run/current-system
        # would then re-activate the OLD gen and silently revert home.file changes.
        #
        # Resolution strategy:
        #  1. Take the LATEST system-*-link by mtime — this is the gen just
        #     built, not whichever one /nix/var/nix/profiles/system happens to
        #     symlink to (`profiles/system` can lag mid-activation).
        #  2. From its `activate` script, grep the activation-<user> path
        #     using a USER-SPECIFIC pattern (the original `-[a-z_-]+` regex
        #     could match `activation-scripts` or similar before reaching
        #     `activation-paper`).
        #  3. Exec the HM-generation `activate` referenced inside.
        #  4. Fail loudly if any of the above misses; do NOT silently skip.
        set -l latest_system (ls -1dt /nix/var/nix/profiles/system-*-link 2>/dev/null | head -1)
        echo "  latest_system = $latest_system"
        if test -z "$latest_system"; or not test -f "$latest_system/activate"
            echo "WARN: could not locate latest system generation under /nix/var/nix/profiles/" >&2
            echo "      HM activation skipped. ~/.local/bin symlinks may be stale." >&2
            return 1
        end
        # No sudo needed — system/*-link/activate is world-readable. Sudo
        # caused intermittent silent empties on past runs (TTY-less prompt
        # eaten by background invocations).
        set -l act_user (grep -hoE "/nix/store/[a-z0-9]+-activation-$USER" $latest_system/activate | head -1)
        echo "  activation-$USER = $act_user"
        if test -z "$act_user"; or not test -f "$act_user"
            echo "WARN: could not locate activation-$USER path in $latest_system/activate" >&2
            echo "      HM activation skipped. ~/.local/bin symlinks may be stale." >&2
            return 1
        end
        set -l hm_gen (grep -hoE '/nix/store/[a-z0-9]+-home-manager-generation' $act_user | head -1)
        echo "  home-manager-generation = $hm_gen"
        if test -z "$hm_gen"; or not test -x "$hm_gen/activate"
            echo "WARN: could not locate home-manager-generation under $act_user" >&2
            echo "      HM activation skipped. ~/.local/bin symlinks may be stale." >&2
            return 1
        end
        echo "Running home-manager activation ($hm_gen)…"
        "$hm_gen/activate"
        or begin
            echo "ERROR: home-manager activation FAILED. Review output above." >&2
            return 1
        end

        # Sanity check: HM profile generation count should have grown by 1.
        # If not, the activate script was a no-op (rare but possible) — flag
        # it so the user knows something's off before they assume everything
        # is current.
        set -l hm_after (count /Users/$USER/.local/state/nix/profiles/home-manager-*-link 2>/dev/null)
        if test "$hm_after" -le "$hm_before"
            echo "NOTE: home-manager profile generation count did not increase ($hm_before → $hm_after)." >&2
            echo "      Either there was nothing to change for the user, or activation no-op'd." >&2
        end

        if test $rebuild_status -ne 0
            echo "darwin-rebuild switch had exited $rebuild_status (see WARN above). HM activation completed regardless." >&2
            return $rebuild_status
        end
    else
        # Linux (e.g. the remote devbox). No nix-darwin — just home-manager.
        # Pick the arch-specific output so x86_64 / aarch64 (Graviton) both
        # resolve without env munging.
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
        set -l target "$flake#$USER@$suffix"
        echo "Switching home-manager → $target ..."
        # First activation may need experimental-features enabled before our
        # xdg.configFile nix.conf lands. Inject via NIX_CONFIG defensively.
        if command -q home-manager
            NIX_CONFIG='experimental-features = nix-command flakes' \
                home-manager switch --flake $target $override --impure $argv
        else
            NIX_CONFIG='experimental-features = nix-command flakes' \
                nix run home-manager/release-25.11 -- switch --flake $target $override --impure $argv
        end
    end
end
