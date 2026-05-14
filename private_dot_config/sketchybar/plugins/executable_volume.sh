#!/bin/bash
VOL=$(osascript -e "output volume of (get volume settings)")
MUTED=$(osascript -e "output muted of (get volume settings)")
if [[ "$MUTED" == "true" ]]; then ICON=""; else ICON=""; fi
echo "icon=$ICON label=${VOL}%"
