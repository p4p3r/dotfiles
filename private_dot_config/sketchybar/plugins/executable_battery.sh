#!/bin/bash
INFO=$(pmset -g batt)
PERCENT=$(echo "$INFO" | grep -Eo "[0-9]+%" | head -1 | tr -d '%')
STATE=$(echo "$INFO" | grep "AC Power")
ICON=""
if [[ $PERCENT -lt 20 ]]; then ICON=""
elif [[ $PERCENT -lt 40 ]]; then ICON=""
elif [[ $PERCENT -lt 60 ]]; then ICON=""
elif [[ $PERCENT -lt 80 ]]; then ICON=""
fi
if [[ -n "$STATE" ]]; then ICON=""; fi
echo "icon=$ICON label=${PERCENT}%"
