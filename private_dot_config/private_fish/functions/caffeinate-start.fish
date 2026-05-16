function caffeinate-start -d "Start preventing macOS sleep (manual control)"
    # Check if already running
    if pgrep -f "caffeinate -is" > /dev/null
        echo "Caffeinate is already running"
        return 0
    end

    # Start caffeinate in background
    caffeinate -is &
    set -g CAFFEINATE_PID $last_pid

    echo "✓ Sleep prevention started (PID: $CAFFEINATE_PID)"
    echo "  System will not sleep until you run: caffeinate-stop"
end
