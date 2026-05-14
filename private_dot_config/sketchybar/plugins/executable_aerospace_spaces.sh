#!/bin/bash
ACTIVE=$(aerospace focused-workspace 2>/dev/null)
SPACES=$(aerospace list-workspaces 2>/dev/null)
LABEL=""
for S in $SPACES; do
  if [[ "$S" = "$ACTIVE" ]]; then
    LABEL="$LABEL [$S]"
  else
    LABEL="$LABEL  $S "
  fi
done
echo "label=$LABEL"
