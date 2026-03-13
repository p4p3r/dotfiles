function claude-squad -d "Launch Claude Code with Agent Teams + sleep prevention"
    set -x CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS 1
    caffeinate -dis claude $argv
end
