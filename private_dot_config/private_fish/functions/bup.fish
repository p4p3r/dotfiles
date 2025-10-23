# Update (one or multiple) selected application(s)
# mnemonic [B]rew [U]pdate [P]lugin
function bup
    set -l upd (brew leaves | fzf -m)

    if test -n "$upd"
        for prog in $upd
            brew upgrade $prog
        end
    end
end
