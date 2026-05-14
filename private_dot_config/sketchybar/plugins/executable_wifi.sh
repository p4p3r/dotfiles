#!/bin/bash
SSID=$(networksetup -getairportnetwork en0 2>/dev/null | sed 's/^Current Wi-Fi Network: //')
if [[ "$SSID" == "You are not associated with an AirPort network."* ]]; then
  SSID="Not connected"
fi
echo "icon= label=$SSID"
