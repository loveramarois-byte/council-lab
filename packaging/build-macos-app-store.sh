#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")"
MODE="${COUNCIL_APP_STORE_MODE:-preview}"
OUTPUT_ROOT="${1:-$PROJECT_DIR/artifacts/app-store}"
BUNDLE_ID="${COUNCIL_APP_STORE_BUNDLE_ID:-io.council-lab.desktop}"
BUILD_NUMBER="${COUNCIL_BUILD_NUMBER:-$(date -u +%Y%m%d%H%M)}"
APP_SIGN_IDENTITY="${COUNCIL_APP_SIGN_IDENTITY:--}"
INSTALLER_SIGN_IDENTITY="${COUNCIL_INSTALLER_SIGN_IDENTITY:-}"
PROVISIONING_PROFILE="${COUNCIL_PROVISIONING_PROFILE:-}"
OUTER_ENTITLEMENTS="$PROJECT_DIR/macos/CouncilNative/Resources/CouncilAppStore.entitlements"
CHILD_ENTITLEMENTS="$PROJECT_DIR/macos/CouncilNative/Resources/CouncilAppStoreChild.entitlements"
PRIVACY_MANIFEST="$PROJECT_DIR/macos/CouncilNative/Resources/PrivacyInfo.xcprivacy"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/council-app-store.XXXXXX")"

if [[ "$MODE" != "preview" && "$MODE" != "production" ]]; then
  echo "COUNCIL_APP_STORE_MODE must be preview or production." >&2
  exit 2
fi

cleanup() {
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

require_identity() {
  local identity="$1"
  local label="$2"
  if [[ -z "$identity" || "$identity" == "-" ]]; then
    echo "Missing $label identity." >&2
    exit 2
  fi
  if ! /usr/bin/security find-identity -v | /usr/bin/grep -F -- "$identity" >/dev/null; then
    echo "$label identity is not available in the current keychain: $identity" >&2
    exit 2
  fi
}

if [[ "$MODE" == "production" ]]; then
  require_identity "$APP_SIGN_IDENTITY" "Mac App Distribution"
  require_identity "$INSTALLER_SIGN_IDENTITY" "Mac Installer Distribution"
  if [[ ! -f "$PROVISIONING_PROFILE" ]]; then
    echo "Missing App Store Connect provisioning profile: $PROVISIONING_PROFILE" >&2
    exit 2
  fi
  PROFILE_PLIST="$TEMP_ROOT/profile.plist"
  /usr/bin/security cms -D -i "$PROVISIONING_PROFILE" > "$PROFILE_PLIST"
  PROFILE_APP_ID="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' "$PROFILE_PLIST" 2>/dev/null || true)"
  PROFILE_DEBUG="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:get-task-allow' "$PROFILE_PLIST" 2>/dev/null || true)"
  if [[ "$PROFILE_APP_ID" != *".$BUNDLE_ID" ]]; then
    echo "Provisioning profile does not match bundle identifier $BUNDLE_ID." >&2
    exit 2
  fi
  if [[ "$PROFILE_DEBUG" == "true" ]]; then
    echo "A development provisioning profile cannot be used for App Store submission." >&2
    exit 2
  fi
fi

if [[ -n "${COUNCIL_APP_STORE_SOURCE_APP:-}" ]]; then
  SOURCE_APP="$COUNCIL_APP_STORE_SOURCE_APP"
else
  DIRECT_OUTPUT="$TEMP_ROOT/direct"
  "$PROJECT_DIR/packaging/build-macos-release.sh" "$DIRECT_OUTPUT" >/dev/null
  SOURCE_APP="$DIRECT_OUTPUT/Council-v${VERSION}-macOS/Council.app"
fi

for required in \
  "$SOURCE_APP/Contents/Resources/backend/council-backend/council-backend" \
  "$SOURCE_APP/Contents/Resources/runtime/node" \
  "$SOURCE_APP/Contents/Resources/web/server.js" \
  "$SOURCE_APP/Contents/Resources/web-build-id.txt"; do
  if [[ ! -e "$required" ]]; then
    echo "App Store source payload is incomplete: $required" >&2
    exit 2
  fi
done

SOURCE_VERSION="$(tr -d '[:space:]' < "$SOURCE_APP/Contents/Resources/VERSION")"
if [[ "$SOURCE_VERSION" != "$VERSION" ]]; then
  echo "App Store source payload version $SOURCE_VERSION does not match repository version $VERSION." >&2
  exit 2
fi

mkdir -p "$OUTPUT_ROOT"
if [[ "$MODE" == "production" ]]; then
  ARTIFACT_BASENAME="Council-v${VERSION}-Mac-App-Store"
else
  ARTIFACT_BASENAME="Council-v${VERSION}-Mac-App-Store-preview-NOT-FOR-UPLOAD"
fi
APP_PATH="$OUTPUT_ROOT/$ARTIFACT_BASENAME.app"
PKG_PATH="$OUTPUT_ROOT/$ARTIFACT_BASENAME.pkg"
rm -rf "$APP_PATH" "$PKG_PATH"
/usr/bin/ditto "$SOURCE_APP" "$APP_PATH"

NATIVE_STAGE="$TEMP_ROOT/native/Council.app"
if [[ -n "${COUNCIL_NATIVE_ARCHS:-}" ]]; then
  NATIVE_ARCHS="$COUNCIL_NATIVE_ARCHS"
elif [[ "$MODE" == "production" ]]; then
  NATIVE_ARCHS="universal"
else
  NATIVE_ARCHS="host"
fi
COUNCIL_SKIP_SIGN=1 \
COUNCIL_NATIVE_ARCHS="$NATIVE_ARCHS" \
COUNCIL_WEB_BUILD_ID_FILE="$APP_PATH/Contents/Resources/web-build-id.txt" \
  "$PROJECT_DIR/macos/CouncilNative/build-app.sh" "$NATIVE_STAGE" >/dev/null
/usr/bin/ditto "$NATIVE_STAGE/Contents/MacOS/CouncilNative" "$APP_PATH/Contents/MacOS/CouncilNative"

RESOURCES="$APP_PATH/Contents/Resources"
rm -rf "$RESOURCES/launcher"
rm -f "$RESOURCES/project-path.txt"
find "$APP_PATH" -name '.DS_Store' -delete
cp "$PRIVACY_MANIFEST" "$RESOURCES/PrivacyInfo.xcprivacy"
if [[ "$MODE" == "production" ]]; then
  cp "$PROVISIONING_PROFILE" "$APP_PATH/Contents/embedded.provisionprofile"
else
  rm -f "$APP_PATH/Contents/embedded.provisionprofile"
  printf '%s\n' \
    "This package uses ad-hoc signatures for local sandbox testing only." \
    "It cannot be uploaded to App Store Connect." \
    > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.txt"
fi

INFO_PLIST="$APP_PATH/Contents/Info.plist"
set_plist_value() {
  local key="$1"
  local type="$2"
  local value="$3"
  /usr/libexec/PlistBuddy -c "Set :$key $value" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :$key $type $value" "$INFO_PLIST"
}
set_plist_value CFBundleIdentifier string "$BUNDLE_ID"
set_plist_value CFBundleShortVersionString string "$VERSION"
set_plist_value CFBundleVersion string "$BUILD_NUMBER"
set_plist_value CouncilDistribution string app-store
set_plist_value ITSAppUsesNonExemptEncryption bool false
set_plist_value NSDocumentsFolderUsageDescription string "仅在您明确选择文件时读取或保存审议资料。"

/usr/bin/plutil -lint "$INFO_PLIST" "$PRIVACY_MANIFEST" "$OUTER_ENTITLEMENTS" "$CHILD_ENTITLEMENTS"
/usr/bin/xattr -cr "$APP_PATH"

if [[ "$MODE" == "production" ]]; then
  SIGN_OPTIONS=(--timestamp --options runtime)
else
  SIGN_OPTIONS=(--timestamp=none)
fi

MAIN_EXECUTABLE="$APP_PATH/Contents/MacOS/CouncilNative"
BACKEND_EXECUTABLE="$RESOURCES/backend/council-backend/council-backend"
NODE_EXECUTABLE="$RESOURCES/runtime/node"

# Sign every nested Mach-O first. Child executables and the outer app receive their entitlements afterward.
while IFS= read -r -d '' candidate; do
  if [[ "$candidate" == "$MAIN_EXECUTABLE" || "$candidate" == "$BACKEND_EXECUTABLE" || "$candidate" == "$NODE_EXECUTABLE" ]]; then
    continue
  fi
  if /usr/bin/file -b "$candidate" | /usr/bin/grep -q 'Mach-O'; then
    /usr/bin/codesign --force --sign "$APP_SIGN_IDENTITY" "${SIGN_OPTIONS[@]}" "$candidate"
  fi
done < <(/usr/bin/find "$APP_PATH" -type f -print0)

for child in "$BACKEND_EXECUTABLE" "$NODE_EXECUTABLE"; do
  /usr/bin/codesign --force --sign "$APP_SIGN_IDENTITY" "${SIGN_OPTIONS[@]}" \
    --entitlements "$CHILD_ENTITLEMENTS" "$child"
done
/usr/bin/codesign --force --sign "$APP_SIGN_IDENTITY" "${SIGN_OPTIONS[@]}" \
  --entitlements "$OUTER_ENTITLEMENTS" "$APP_PATH"

/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP_PATH"
/usr/bin/codesign -d --entitlements :- "$APP_PATH" > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.app-entitlements.plist" 2>/dev/null
/usr/bin/codesign -d --entitlements :- "$BACKEND_EXECUTABLE" > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.child-entitlements.plist" 2>/dev/null
/usr/bin/codesign -d --entitlements :- "$NODE_EXECUTABLE" > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.node-entitlements.plist" 2>/dev/null
/usr/bin/plutil -lint \
  "$OUTPUT_ROOT/$ARTIFACT_BASENAME.app-entitlements.plist" \
  "$OUTPUT_ROOT/$ARTIFACT_BASENAME.child-entitlements.plist" \
  "$OUTPUT_ROOT/$ARTIFACT_BASENAME.node-entitlements.plist"

if [[ -e "$RESOURCES/launcher/update-council.sh" ]]; then
  echo "Direct updater leaked into the App Store payload." >&2
  exit 2
fi
if [[ "$(/usr/libexec/PlistBuddy -c 'Print :CouncilDistribution' "$INFO_PLIST")" != "app-store" ]]; then
  echo "App Store distribution marker is missing." >&2
  exit 2
fi

PACKAGE_COMPONENT="$TEMP_ROOT/package-component/Council.app"
mkdir -p "$(dirname "$PACKAGE_COMPONENT")"
/usr/bin/ditto "$APP_PATH" "$PACKAGE_COMPONENT"
if [[ "$MODE" == "production" ]]; then
  /usr/bin/productbuild --component "$PACKAGE_COMPONENT" /Applications \
    --sign "$INSTALLER_SIGN_IDENTITY" "$PKG_PATH"
else
  /usr/bin/productbuild --component "$PACKAGE_COMPONENT" /Applications "$PKG_PATH"
fi
if [[ "$MODE" == "production" ]]; then
  /usr/sbin/pkgutil --check-signature "$PKG_PATH" > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.pkg-signature.txt" 2>&1
else
  set +e
  /usr/sbin/pkgutil --check-signature "$PKG_PATH" > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.pkg-signature.txt" 2>&1
  PREVIEW_SIGNATURE_STATUS=$?
  set -e
  if [[ $PREVIEW_SIGNATURE_STATUS -ne 0 ]] \
    && ! /usr/bin/grep -F "Status: no signature" "$OUTPUT_ROOT/$ARTIFACT_BASENAME.pkg-signature.txt" >/dev/null; then
    echo "Unexpected preview package signature validation failure." >&2
    exit 2
  fi
fi
/usr/sbin/pkgutil --payload-files "$PKG_PATH" > "$OUTPUT_ROOT/$ARTIFACT_BASENAME.pkg-payload.txt"
if ! /usr/bin/grep -F './Council.app/Contents/MacOS/CouncilNative' \
  "$OUTPUT_ROOT/$ARTIFACT_BASENAME.pkg-payload.txt" >/dev/null; then
  echo "Installer payload does not contain the canonical Council.app component." >&2
  exit 2
fi

echo "$PKG_PATH"
