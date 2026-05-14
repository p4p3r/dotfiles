#!/bin/bash
# Emit a Bartender-style Bluetooth indicator
ICON=""
LABEL="Off"

if command -v blueutil >/dev/null 2>&1; then
  if [[ "$(blueutil --power)" == "1" ]]; then
    CONNECTED=$(blueutil --connected 2>/dev/null | grep -c "connected = yes")
    if [[ "$CONNECTED" -gt 0 ]]; then
      LABEL="${CONNECTED} dev"
    else
      LABEL="On"
    fi
  fi
else
  STATE=$(defaults read /Library/Preferences/com.apple.Bluetooth ControllerPowerState 2>/dev/null)
  if [[ "$STATE" == "1" ]]; then
    LABEL="On"
  fi
fi

echo "icon=$ICON label=$LABEL"

