#!/bin/zsh

set -u
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_EXE="$RESOURCES_DIR/backend/council-backend/council-backend"
NODE_EXE="$RESOURCES_DIR/runtime/node"
WEB_DIR="$RESOURCES_DIR/web"
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council-bundled.pids"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

mkdir -p "$LOG_DIR"
: > "$PID_FILE"

show_error() {
  /usr/bin/osascript -e "display dialog \"$1\" buttons {\"好\"} with title \"Council 无法启动\"" >/dev/null 2>&1 || true
}

is_up() {
  /usr/bin/curl -fsS --max-time 2 "$1" >/dev/null 2>&1
}

port_is_used() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for() {
  local url="$1"
  local attempts=0
  while (( attempts < 60 )); do
    is_up "$url" && return 0
    /bin/sleep 0.25
    attempts=$((attempts + 1))
  done
  return 1
}

if [[ ! -x "$BACKEND_EXE" || ! -x "$NODE_EXE" || ! -f "$WEB_DIR/server.js" ]]; then
  show_error "安装包不完整，请重新下载并解压 Council。"
  exit 1
fi

if ! is_up "http://127.0.0.1:8001/api/health"; then
  if port_is_used 8001; then
    show_error "端口 8001 已被其他程序占用，请先关闭该程序。"
    exit 1
  fi
  /usr/bin/nohup "$BACKEND_EXE" >>"$BACKEND_LOG" 2>&1 &
  backend_pid=$!
  echo "backend $backend_pid" >> "$PID_FILE"
  if ! wait_for "http://127.0.0.1:8001/api/health"; then
    show_error "后端启动失败，请查看 ~/Library/Logs/Council/backend.log。"
    exit 1
  fi
fi

if ! is_up "http://127.0.0.1:3000/"; then
  if port_is_used 3000; then
    show_error "端口 3000 已被其他程序占用，请先关闭该程序。"
    exit 1
  fi
  pushd "$WEB_DIR" >/dev/null
  HOSTNAME=127.0.0.1 PORT=3000 NODE_ENV=production NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 \
    /usr/bin/nohup "$NODE_EXE" "$WEB_DIR/server.js" >>"$FRONTEND_LOG" 2>&1 &
  frontend_pid=$!
  popd >/dev/null
  echo "frontend $frontend_pid" >> "$PID_FILE"
  if ! wait_for "http://127.0.0.1:3000/"; then
    show_error "网页启动失败，请查看 ~/Library/Logs/Council/frontend.log。"
    exit 1
  fi
fi

/usr/bin/open "http://localhost:3000"
