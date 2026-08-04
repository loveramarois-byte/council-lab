#!/bin/zsh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_INSTALL_DIR="${COUNCIL_APP_INSTALL_DIR:-$HOME/Desktop}"
DEST_APP="$APP_INSTALL_DIR/Council.app"

"$PROJECT_DIR/macos/CouncilNative/build-app.sh" "$DEST_APP"
/usr/bin/xattr -dr com.apple.quarantine "$DEST_APP" 2>/dev/null || true
