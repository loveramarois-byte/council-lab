#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEST_APP="${1:-$PROJECT_DIR/artifacts/Council-Native.app}"
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")"
WEB_BUILD_ID_FILE="${COUNCIL_WEB_BUILD_ID_FILE:-$PROJECT_DIR/frontend/.next-runtime/BUILD_ID}"
BUILD_ROOT="$PROJECT_DIR/build/council-native"
STAGE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/council-native.XXXXXX")"
STAGE_APP="$STAGE_ROOT/Council.app"

if [[ ! -s "$WEB_BUILD_ID_FILE" ]]; then
  echo "Missing frontend Build ID: $WEB_BUILD_ID_FILE" >&2
  exit 1
fi

cleanup() {
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

mkdir -p "$STAGE_APP/Contents/MacOS" "$STAGE_APP/Contents/Resources"

if [[ "${COUNCIL_NATIVE_ARCHS:-universal}" == "universal" ]]; then
  for architecture in arm64 x86_64; do
    swift build \
      --package-path "$SCRIPT_DIR" \
      --scratch-path "$BUILD_ROOT/$architecture" \
      --triple "$architecture-apple-macosx14.0" \
      -c release
  done
  ARM_BIN="$(swift build --package-path "$SCRIPT_DIR" --scratch-path "$BUILD_ROOT/arm64" --triple arm64-apple-macosx14.0 -c release --show-bin-path)/CouncilNative"
  INTEL_BIN="$(swift build --package-path "$SCRIPT_DIR" --scratch-path "$BUILD_ROOT/x86_64" --triple x86_64-apple-macosx14.0 -c release --show-bin-path)/CouncilNative"
  /usr/bin/lipo -create "$ARM_BIN" "$INTEL_BIN" -output "$STAGE_APP/Contents/MacOS/CouncilNative"
else
  swift build \
    --package-path "$SCRIPT_DIR" \
    --scratch-path "$BUILD_ROOT/host" \
    -c release
  BIN_DIR="$(swift build --package-path "$SCRIPT_DIR" --scratch-path "$BUILD_ROOT/host" -c release --show-bin-path)"
  cp "$BIN_DIR/CouncilNative" "$STAGE_APP/Contents/MacOS/CouncilNative"
fi
cp "$SCRIPT_DIR/Resources/Info.plist" "$STAGE_APP/Contents/Info.plist"
cp "$PROJECT_DIR/desktop/Council.icns" "$STAGE_APP/Contents/Resources/Council.icns"
cp "$WEB_BUILD_ID_FILE" "$STAGE_APP/Contents/Resources/web-build-id.txt"
printf '%s\n' "$PROJECT_DIR" > "$STAGE_APP/Contents/Resources/project-path.txt"
chmod +x "$STAGE_APP/Contents/MacOS/CouncilNative"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$STAGE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $(date +%Y%m%d%H%M)" "$STAGE_APP/Contents/Info.plist"
/usr/bin/plutil -lint "$STAGE_APP/Contents/Info.plist"

if [[ "${COUNCIL_SKIP_SIGN:-0}" != "1" ]]; then
  /usr/bin/codesign --force --deep --sign - "$STAGE_APP"
  /usr/bin/codesign --verify --deep --strict "$STAGE_APP"
fi

mkdir -p "$(dirname "$DEST_APP")"
rm -rf "$DEST_APP"
/usr/bin/ditto "$STAGE_APP" "$DEST_APP"
echo "Built $DEST_APP"
