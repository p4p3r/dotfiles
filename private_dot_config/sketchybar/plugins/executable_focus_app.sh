#!/bin/bash
APP=$(aerospace focused-window app-name 2>/dev/null)
if [[ -z "$APP" ]]; then
  APP=$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true')
fi
echo "label=$APP"
