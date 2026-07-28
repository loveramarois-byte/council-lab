#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

fail() {
  printf '\n安装未完成：%s\n' "$1" >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || fail "需要 Python 3.12 或更高版本：https://www.python.org/downloads/"
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
  || fail "Python 版本过低，需要 3.12 或更高版本。"

command -v node >/dev/null 2>&1 || fail "需要 Node.js 22 或更高版本：https://nodejs.org/"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"
[[ "$NODE_MAJOR" =~ ^[0-9]+$ ]] || fail "无法识别 Node.js 版本。"
(( NODE_MAJOR >= 22 )) || fail "Node.js 版本过低，需要 22 或更高版本。"
command -v npm >/dev/null 2>&1 || fail "未找到 npm，请重新安装 Node.js。"

printf '1/3 安装后端依赖...\n'
if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
fi
"$BACKEND_DIR/.venv/bin/python" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
  || fail "现有 backend/.venv 版本过低，请删除该目录后重新安装。"
"$BACKEND_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$BACKEND_DIR/requirements.lock"

printf '2/3 安装并构建网页...\n'
(
  cd "$FRONTEND_DIR"
  npm ci --no-audit --no-fund
  npm run build
)

printf '3/3 创建启动入口...\n'
chmod +x "$SCRIPT_DIR/start.sh" "$SCRIPT_DIR/desktop/"*.sh "$SCRIPT_DIR/desktop/Council.command"
if [[ "$(uname -s)" == "Darwin" ]]; then
  "$SCRIPT_DIR/desktop/build-macos-app.sh"
fi

printf '\nCouncil 安装完成。\n'
if [[ "$(uname -s)" == "Darwin" ]]; then
  printf '以后双击桌面的 Council.app 即可。\n'
else
  printf '运行 ./start.sh 启动。\n'
fi
