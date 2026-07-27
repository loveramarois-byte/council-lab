#!/bin/zsh

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council.pids"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

mkdir -p "$LOG_DIR"
: > "$PID_FILE"

is_up() {
  curl -fsS --max-time 1 "$1" >/dev/null 2>&1
}

frontend_is_up() {
  local html css_path
  html="$(curl -fsS --max-time 2 "http://127.0.0.1:3000/" 2>/dev/null)" || return 1
  css_path="$(printf '%s' "$html" | sed -n 's/.*href="\([^\"]*\.css[^\"]*\)".*/\1/p' | head -n 1)"
  [[ -n "$css_path" ]] || return 1
  curl -fsS --max-time 2 "http://127.0.0.1:3000$css_path" >/dev/null 2>&1
}

wait_for() {
  local url="$1"
  local attempts=0
  while (( attempts < 40 )); do
    is_up "$url" && return 0
    sleep 0.25
    attempts=$((attempts + 1))
  done
  return 1
}

if [[ ! -x "$BACKEND_DIR/.venv/bin/uvicorn" ]]; then
  osascript -e 'display dialog "尚未安装运行环境。请双击项目文件夹里的“安装 Council.command”。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
  exit 1
fi

if [[ ! -x "$FRONTEND_DIR/node_modules/next/dist/bin/next" || ! -f "$FRONTEND_DIR/.next/BUILD_ID" ]]; then
  osascript -e 'display dialog "网页尚未构建。请双击项目文件夹里的“安装 Council.command”。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
  exit 1
fi

if ! is_up "http://127.0.0.1:8001/api/health"; then
  pushd "$BACKEND_DIR" >/dev/null
  nohup "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8001 >>"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  popd >/dev/null
  echo "backend $BACKEND_PID" >>"$PID_FILE"
  if ! wait_for "http://127.0.0.1:8001/api/health"; then
    osascript -e 'display dialog "后端启动失败，请查看 ~/Library/Logs/Council/backend.log" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
    exit 1
  fi
fi

if ! frontend_is_up; then
  EXISTING_FRONTEND_PID="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null | head -n 1)"
  if [[ -n "$EXISTING_FRONTEND_PID" ]]; then
    EXISTING_FRONTEND_COMMAND="$(ps -p "$EXISTING_FRONTEND_PID" -o command= 2>/dev/null || true)"
    if [[ "$EXISTING_FRONTEND_COMMAND" == *"$FRONTEND_DIR"* || "$EXISTING_FRONTEND_COMMAND" == *"next-server"* ]]; then
      kill "$EXISTING_FRONTEND_PID" >/dev/null 2>&1 || true
      sleep 1
    else
      osascript -e 'display dialog "端口 3000 已被其他程序占用，请先关闭该程序。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
      exit 1
    fi
  fi
  pushd "$FRONTEND_DIR" >/dev/null
  NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 nohup "$FRONTEND_DIR/node_modules/next/dist/bin/next" start -p 3000 >>"$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!
  popd >/dev/null
  echo "frontend $FRONTEND_PID" >>"$PID_FILE"
  attempts=0
  until frontend_is_up || (( attempts >= 40 )); do
    sleep 0.25
    attempts=$((attempts + 1))
  done
  if ! frontend_is_up; then
    osascript -e 'display dialog "前端启动失败，请查看 ~/Library/Logs/Council/frontend.log" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
    exit 1
  fi
fi

open "http://localhost:3000"
