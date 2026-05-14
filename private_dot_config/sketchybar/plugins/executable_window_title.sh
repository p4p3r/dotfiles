#!/bin/bash
TITLE=$(aerospace focused-window title 2>/dev/null)
MAX_LEN=60
if [[ ${#TITLE} -gt $MAX_LEN ]]; then
  TITLE="${TITLE:0:$MAX_LEN}…"
fi
echo "label=$TITLE"
