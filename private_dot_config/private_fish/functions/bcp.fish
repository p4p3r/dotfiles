# Delete (one or multiple) selected application(s)
# mnemonic [B]rew [C]lean [P]lugin (e.g. uninstall)
function bcp
    set -l uninst (brew leaves | fzf -m)

    if test -n "$uninst"
        for prog in $uninst
            brew uninstall $prog
        end
    end
end
