function z
    # If any arguments are given, delegate to _z and return.
    if test (count $argv) -gt 0
        _z $argv
        return
    end

    # No arguments: launch interactive mode.
    # Note: Since no arguments are provided, the query is empty.
    set -l target (_z -l 2>&1 | fzf --height 40% --nth 2.. --reverse --inline-info +s --tac --query "" | sed 's/^[0-9,.]* *//')
    cd $target
end
