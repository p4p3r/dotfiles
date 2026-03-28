function claude-squad -d "Launch Claude Code with Agent Teams + sleep prevention"
    set -e ANTHROPIC_API_KEY
    set -x CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS 1
    caffeinate -is claude $argv
end
