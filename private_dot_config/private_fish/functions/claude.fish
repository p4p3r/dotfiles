function claude -d "Launch Claude Code with sleep prevention" --wraps claude
    # Mac: `caffeinate -is` keeps the system awake while claude runs (laptop
    # lid closed = no sleep mid-session).
    # Linux: caffeinate doesn't exist. Devboxes / servers don't suspend, so
    # just exec claude directly. (On a Linux LAPTOP you'd swap this for
    # `systemd-inhibit --what=idle:sleep` — add if/when that comes up.)
    if test (uname) = Darwin
        SHELL=(command -s fish) caffeinate -is command claude $argv
    else
        SHELL=(command -s fish) command claude $argv
    end
end
