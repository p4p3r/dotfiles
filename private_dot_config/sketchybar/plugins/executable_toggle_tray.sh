#!/bin/bash
HIDDEN_ITEMS=( tray_bt tray_battery )
STATE=$(sketchybar --query "${HIDDEN_ITEMS[0]}" | jq -r '.drawing')
if [[ "$STATE" == "on" ]]; then
  NEW_STATE="off"; ICON="▾"
else
  NEW_STATE="on"; ICON="▴"
fi
for ITEM in "${HIDDEN_ITEMS[@]}"; do
  sketchybar --set "$ITEM" drawing="$NEW_STATE"
done
sketchybar --set tray_toggle icon="$ICON"
