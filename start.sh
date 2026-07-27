#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(uname -s)" == "Darwin" ]]; then
  exec "$SCRIPT_DIR/desktop/start-council.sh"
fi

printf '当前一键启动器支持 macOS。其他系统请查看 docs/INSTALL.md。\n' >&2
exit 1
