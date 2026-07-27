#!/bin/zsh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
/bin/zsh "$SCRIPT_DIR/Council.app/Contents/Resources/launcher/stop-council.sh"
