function claude -d "Launch Claude Code with sleep prevention" --wraps claude
    SHELL=(command -s fish) caffeinate -is command claude $argv
end
