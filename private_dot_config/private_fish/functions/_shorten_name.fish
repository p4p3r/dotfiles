function _shorten_name -d "Abbreviate a name by taking first 2 chars of each part split on - and _"
    set -l name $argv[1]
    # Replace _ with - for uniform splitting
    set -l parts (string split -- '-' (string replace -a '_' '-' $name))
    set -l short
    for part in $parts
        set -a short (string sub -l 2 -- $part)
    end
    string join '' $short
end
