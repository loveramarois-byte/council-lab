#!/bin/zsh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_INSTALL_DIR="${COUNCIL_APP_INSTALL_DIR:-$HOME/Desktop}"
DEST_APP="$APP_INSTALL_DIR/Council.app"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/council-app.XXXXXX")"
APP_DIR="$BUILD_DIR/Council.app"

cleanup() {
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

/usr/bin/osacompile -o "$APP_DIR" "$SCRIPT_DIR/Council.applescript"
cp "$SCRIPT_DIR/Council.icns" "$APP_DIR/Contents/Resources/Council.icns"
printf '%s\n' "$PROJECT_DIR" > "$APP_DIR/Contents/Resources/project-path.txt"

/usr/libexec/PlistBuddy -c "Set :CFBundleName Council" "$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Council" "$APP_DIR/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string Council" "$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier io.council-lab.desktop" "$APP_DIR/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string io.council-lab.desktop" "$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile Council.icns" "$APP_DIR/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string Council.icns" "$APP_DIR/Contents/Info.plist"

/usr/bin/codesign --force --deep --sign - "$APP_DIR"
/usr/bin/xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true
mkdir -p "$APP_INSTALL_DIR"
rm -rf "$DEST_APP"
/usr/bin/ditto "$APP_DIR" "$DEST_APP"
/usr/bin/codesign --verify --deep --strict "$DEST_APP"
/usr/bin/xattr -dr com.apple.quarantine "$DEST_APP" 2>/dev/null || true
echo "Built $DEST_APP"
