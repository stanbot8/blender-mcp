#!/bin/bash
# Install addon.py to Blender, keeping exactly one rollback backup.
# Usage: bash install.sh

SRC="$(dirname "$0")/addon.py"
DEST="$APPDATA/Blender Foundation/Blender/5.0/extensions/addon.py"
BAK="$DEST.bak"

if [ ! -f "$SRC" ]; then
  echo "ERROR: addon.py not found at $SRC"
  exit 1
fi

# Rotate: delete old backup, move current → backup
if [ -f "$DEST" ]; then
  cp -f "$DEST" "$BAK"
  echo "Backed up previous version to addon.py.bak"
fi

cp -f "$SRC" "$DEST"
echo "Installed addon.py to Blender 5.0"
echo "Restart Blender to apply changes."
echo "To rollback: cp \"$BAK\" \"$DEST\""
