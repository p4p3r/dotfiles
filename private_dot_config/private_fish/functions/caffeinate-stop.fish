function caffeinate-stop -d "Stop preventing macOS sleep (manual control)"
    # Kill all caffeinate processes started by user
    set pids (pgrep -f "caffeinate -is")

    if test -z "$pids"
        echo "No caffeinate processes found"
        return 0
    end

    for pid in $pids
        kill $pid 2>/dev/null
        echo "✓ Stopped caffeinate (PID: $pid)"
    end

    echo "Sleep prevention stopped - system can sleep normally"
end
