# Install (one or multiple) selected application(s)
# using "brew search" as source input
# mnemonic [B]rew [I]nstall [P]lugin
function bip
    set -l inst (brew search | fzf -m)

    if test -n "$inst"
        for prog in $inst
            brew install $prog
        end
    end
end
