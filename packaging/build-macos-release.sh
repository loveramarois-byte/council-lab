#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")"
OUTPUT_ROOT="${1:-$PROJECT_DIR/artifacts}"
PACKAGE_NAME="Council-v${VERSION}-macOS"
STAGE_DIR="$OUTPUT_ROOT/$PACKAGE_NAME"
ZIP_PATH="$OUTPUT_ROOT/$PACKAGE_NAME.zip"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/backend/.venv/bin/python}"
PYINSTALLER_WORK="$PROJECT_DIR/build/pyinstaller-macos"
PYINSTALLER_DIST="$PROJECT_DIR/dist/pyinstaller-macos"
NODE_RUNTIME_VERSION="${NODE_RUNTIME_VERSION:-22.17.1}"
case "$(uname -m)" in
  arm64) NODE_RUNTIME_ARCH="arm64" ;;
  x86_64) NODE_RUNTIME_ARCH="x64" ;;
  *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
esac
NODE_RUNTIME_NAME="node-v${NODE_RUNTIME_VERSION}-darwin-${NODE_RUNTIME_ARCH}"
NODE_RUNTIME_ARCHIVE="$PROJECT_DIR/build/${NODE_RUNTIME_NAME}.tar.gz"
NODE_RUNTIME_DIR="$PROJECT_DIR/build/$NODE_RUNTIME_NAME"

if [[ "$PYTHON_BIN" != */* ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" || true)"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python build environment not found. Set PYTHON_BIN to a Python executable." >&2
  exit 1
fi

mkdir -p "$OUTPUT_ROOT" "$PROJECT_DIR/build" "$PROJECT_DIR/dist"
rm -rf "$STAGE_DIR" "$ZIP_PATH" "$PYINSTALLER_WORK" "$PYINSTALLER_DIST"

if [[ ! -x "$NODE_RUNTIME_DIR/bin/node" ]]; then
  rm -rf "$NODE_RUNTIME_DIR" "$NODE_RUNTIME_ARCHIVE"
  /usr/bin/curl -fsSL "https://nodejs.org/dist/v${NODE_RUNTIME_VERSION}/${NODE_RUNTIME_NAME}.tar.gz" -o "$NODE_RUNTIME_ARCHIVE"
  /usr/bin/curl -fsSL "https://nodejs.org/dist/v${NODE_RUNTIME_VERSION}/SHASUMS256.txt" -o "$PROJECT_DIR/build/node-SHASUMS256.txt"
  pushd "$PROJECT_DIR/build" >/dev/null
  grep " ${NODE_RUNTIME_NAME}.tar.gz$" node-SHASUMS256.txt | /usr/bin/shasum -a 256 -c -
  /usr/bin/tar -xzf "$NODE_RUNTIME_ARCHIVE"
  popd >/dev/null
fi

pushd "$PROJECT_DIR/frontend" >/dev/null
npm ci --no-audit --no-fund
COUNCIL_STANDALONE=1 NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run build
popd >/dev/null

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name council-backend \
  --paths "$PROJECT_DIR/backend" \
  --collect-all keyring \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --workpath "$PYINSTALLER_WORK" \
  --specpath "$PYINSTALLER_WORK" \
  --distpath "$PYINSTALLER_DIST" \
  "$PROJECT_DIR/backend/desktop_entry.py"

mkdir -p "$STAGE_DIR"
/usr/bin/osacompile -o "$STAGE_DIR/Council.app" "$PROJECT_DIR/desktop/Council.applescript"
RESOURCES_DIR="$STAGE_DIR/Council.app/Contents/Resources"
mkdir -p "$RESOURCES_DIR/backend" "$RESOURCES_DIR/runtime" "$RESOURCES_DIR/launcher"

/usr/bin/ditto "$PYINSTALLER_DIST/council-backend" "$RESOURCES_DIR/backend/council-backend"
/usr/bin/ditto "$PROJECT_DIR/frontend/.next/standalone" "$RESOURCES_DIR/web"
mkdir -p "$RESOURCES_DIR/web/.next"
/usr/bin/ditto "$PROJECT_DIR/frontend/.next/static" "$RESOURCES_DIR/web/.next/static"
cp "$NODE_RUNTIME_DIR/bin/node" "$RESOURCES_DIR/runtime/node"
cp "$PROJECT_DIR/desktop/start-bundled.sh" "$RESOURCES_DIR/launcher/start-council.sh"
cp "$PROJECT_DIR/desktop/stop-bundled.sh" "$RESOURCES_DIR/launcher/stop-council.sh"
cp "$PROJECT_DIR/desktop/Council.icns" "$RESOURCES_DIR/Council.icns"
chmod +x "$RESOURCES_DIR/runtime/node" "$RESOURCES_DIR/launcher/"*.sh "$RESOURCES_DIR/backend/council-backend/council-backend"

/usr/libexec/PlistBuddy -c "Set :CFBundleName Council" "$STAGE_DIR/Council.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Council" "$STAGE_DIR/Council.app/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string Council" "$STAGE_DIR/Council.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier io.council-lab.desktop" "$STAGE_DIR/Council.app/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string io.council-lab.desktop" "$STAGE_DIR/Council.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$STAGE_DIR/Council.app/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$STAGE_DIR/Council.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile Council.icns" "$STAGE_DIR/Council.app/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string Council.icns" "$STAGE_DIR/Council.app/Contents/Info.plist"

cp "$PROJECT_DIR/desktop/Stop Council.command" "$STAGE_DIR/Stop Council.command"
chmod +x "$STAGE_DIR/Stop Council.command"
cp "$PROJECT_DIR/LICENSE" "$PROJECT_DIR/NOTICE" "$STAGE_DIR/"
cp "$PROJECT_DIR/packaging/README-macOS.txt" "$STAGE_DIR/README-FIRST.txt"

/usr/bin/codesign --force --deep --sign - "$STAGE_DIR/Council.app"
/usr/bin/codesign --verify --deep --strict "$STAGE_DIR/Council.app"

pushd "$OUTPUT_ROOT" >/dev/null
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$PACKAGE_NAME" "$PACKAGE_NAME.zip"
popd >/dev/null
echo "$ZIP_PATH"
