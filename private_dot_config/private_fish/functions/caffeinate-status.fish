function caffeinate-status -d "Check if caffeinate is active"
    set pids (pgrep -f "caffeinate")

    if test -z "$pids"
        echo "❌ Sleep prevention: INACTIVE (system can sleep)"
        return 1
    else
        echo "✓ Sleep prevention: ACTIVE (system won't sleep)"
        echo "  Active caffeinate processes:"
        ps aux | grep caffeinate | grep -v grep
        return 0
    end
end
