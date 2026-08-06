#!/bin/zsh

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
FRONTEND_DIST_DIR=".next-runtime"
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council.pids"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
TOKEN_FILE="$LOG_DIR/mobile-access.token"
DESKTOP_TOKEN_FILE="$LOG_DIR/desktop-access.token"
INTERNAL_TOKEN_FILE="$LOG_DIR/backend-access.token"
STARTUP_LOCK_FILE="$LOG_DIR/startup.lock"

mkdir -p "$LOG_DIR"

release_startup_lock() {
  local owner=""
  [[ -f "$STARTUP_LOCK_FILE" ]] && owner="$(tr -d '[:space:]' < "$STARTUP_LOCK_FILE")"
  [[ "$owner" == "$$" ]] && /bin/rm -f "$STARTUP_LOCK_FILE"
}

acquire_startup_lock() {
  local attempts=0
  while (( attempts < 150 )); do
    if /usr/bin/shlock -f "$STARTUP_LOCK_FILE" -p $$; then
      return 0
    fi
    /bin/sleep 0.1
    attempts=$((attempts + 1))
  done
  return 1
}

if ! acquire_startup_lock
then
  osascript -e 'display dialog "Council 正在由另一个窗口启动，请稍后重试。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
  exit 1
fi
trap release_startup_lock EXIT

: > "$PID_FILE"

is_up() {
  curl -fsS --max-time 1 "$1" >/dev/null 2>&1
}

frontend_is_up() {
  local response
  response="$(curl -fsSi --max-time 2 "http://127.0.0.1:3000/mobile-access/health" 2>/dev/null || true)"
  [[ "$response" == *'"service":"council-mobile-access"'* \
    && "$response" == *"\"runtime_id\":\"$COUNCIL_RUNTIME_ID\""* \
    && "$response" == *"\"web_build_id\":\"$FRONTEND_BUILD_ID\""* \
    && "$response" == *"\"internal_api_id\":\"$INTERNAL_API_ID\""* \
    && "${response:l}" == *"x-council-desktop-token-id: $DESKTOP_TOKEN_ID"* ]]
}

backend_is_up() {
  local response
  response="$(curl -fsS --max-time 2 "http://127.0.0.1:8001/api/health" 2>/dev/null || true)"
  [[ "$response" == *'"service":"council-lab"'* \
    && "$response" == *"\"runtime_id\":\"$COUNCIL_RUNTIME_ID\""* \
    && "$response" == *"\"internal_api_id\":\"$INTERNAL_API_ID\""* ]]
}

council_listener_owns_port() {
  local port="$1"
  local response
  if [[ "$port" == "8001" ]]; then
    response="$(curl -fsS --max-time 2 "http://127.0.0.1:8001/api/health" 2>/dev/null || true)"
    [[ "$response" == *'"service":"council-lab"'* \
      && "$response" == *"\"internal_api_id\":\"$INTERNAL_API_ID\""* ]]
  else
    response="$(curl -fsS --max-time 2 "http://127.0.0.1:3000/mobile-access/health" 2>/dev/null || true)"
    [[ "$response" == *'"service":"council-mobile-access"'* \
      && "$response" == *"\"internal_api_id\":\"$INTERNAL_API_ID\""* ]]
  fi
}

stop_project_listener() {
  local port="$1"
  local project_path="$2"
  local pid
  local process_cwd
  local process_command
  local replaceable_council=false
  council_listener_owns_port "$port" && replaceable_council=true
  for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
    [[ "$pid" == <-> ]] || continue
    (( pid > 1 )) || continue
    process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    process_command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$replaceable_council" == true || "$process_cwd" == "$project_path"* || "$process_command" == *"$project_path"* ]]; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  local attempts=0
  while lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; do
    (( attempts >= 30 )) && break
    sleep 0.1
    attempts=$((attempts + 1))
  done
  if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && [[ "$replaceable_council" == true ]]; then
    for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
      [[ "$pid" == <-> ]] || continue
      (( pid > 1 )) || continue
      kill -KILL "$pid" >/dev/null 2>&1 || true
    done
    attempts=0
    while lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; do
      (( attempts >= 20 )) && return 1
      sleep 0.1
      attempts=$((attempts + 1))
    done
  fi
  lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 1
  return 0
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

if [[ ! -x "$FRONTEND_DIR/node_modules/next/dist/bin/next" || ! -f "$FRONTEND_DIR/$FRONTEND_DIST_DIR/BUILD_ID" ]]; then
  osascript -e 'display dialog "网页尚未构建。请双击项目文件夹里的“安装 Council.command”。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
  exit 1
fi

FRONTEND_BUILD_ID="$(tr -d '[:space:]' < "$FRONTEND_DIR/$FRONTEND_DIST_DIR/BUILD_ID")"
export COUNCIL_RUNTIME_ID="source:$FRONTEND_BUILD_ID"
export COUNCIL_WEB_BUILD_ID="$FRONTEND_BUILD_ID"

umask 077
INTERNAL_TOKEN=""
if [[ -f "$INTERNAL_TOKEN_FILE" ]]; then
  INTERNAL_TOKEN="$(tr -d '[:space:]' < "$INTERNAL_TOKEN_FILE")"
fi
if (( ${#INTERNAL_TOKEN} < 32 )); then
  INTERNAL_TOKEN="$(/usr/bin/openssl rand -hex 24)"
  printf '%s\n' "$INTERNAL_TOKEN" > "$INTERNAL_TOKEN_FILE"
fi
chmod 600 "$INTERNAL_TOKEN_FILE"
INTERNAL_API_ID="$(printf '%s' "$INTERNAL_TOKEN" | shasum -a 256 | awk '{print substr($1, 1, 16)}')"

if ! backend_is_up; then
  if lsof -tiTCP:8001 -sTCP:LISTEN >/dev/null 2>&1 && ! stop_project_listener 8001 "$BACKEND_DIR"; then
    osascript -e 'display dialog "端口 8001 已被其他程序占用，请先关闭该程序。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
    exit 1
  fi
  pushd "$BACKEND_DIR" >/dev/null
  COUNCIL_INTERNAL_API_TOKEN="$INTERNAL_TOKEN" nohup "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8001 >>"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  popd >/dev/null
  echo "backend $BACKEND_PID" >>"$PID_FILE"
  if ! wait_for "http://127.0.0.1:8001/api/health" || ! backend_is_up; then
    osascript -e 'display dialog "后端启动失败，请查看 ~/Library/Logs/Council/backend.log" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
    exit 1
  fi
fi

REMOTE_TOKEN=""
DESKTOP_TOKEN=""
DESKTOP_TOKEN_ID=""
if [[ -f "$TOKEN_FILE" && -f "$DESKTOP_TOKEN_FILE" ]]; then
  REMOTE_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  DESKTOP_TOKEN="$(tr -d '[:space:]' < "$DESKTOP_TOKEN_FILE")"
  if (( ${#DESKTOP_TOKEN} >= 32 )); then
    DESKTOP_TOKEN_ID="$(printf '%s' "$DESKTOP_TOKEN" | shasum -a 256 | awk '{print substr($1, 1, 16)}')"
  fi
fi

if ! frontend_is_up; then
  EXISTING_FRONTEND_PID="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null | head -n 1)"
  if [[ -n "$EXISTING_FRONTEND_PID" ]]; then
    if ! stop_project_listener 3000 "$FRONTEND_DIR"; then
      osascript -e 'display dialog "端口 3000 已被其他程序占用，请先关闭该程序。" buttons {"好"} with title "Council 无法启动"' >/dev/null 2>&1 || true
      exit 1
    fi
  fi
  REMOTE_TOKEN="$(/usr/bin/openssl rand -hex 24)"
  DESKTOP_TOKEN="$(/usr/bin/openssl rand -hex 24)"
  DESKTOP_TOKEN_ID="$(printf '%s' "$DESKTOP_TOKEN" | shasum -a 256 | awk '{print substr($1, 1, 16)}')"
  printf '%s\n' "$REMOTE_TOKEN" > "$TOKEN_FILE"
  printf '%s\n' "$DESKTOP_TOKEN" > "$DESKTOP_TOKEN_FILE"
  pushd "$FRONTEND_DIR" >/dev/null
  COUNCIL_NEXT_DIST_DIR="$FRONTEND_DIST_DIR" COUNCIL_REMOTE_TOKEN="$REMOTE_TOKEN" COUNCIL_DESKTOP_TOKEN="$DESKTOP_TOKEN" COUNCIL_INTERNAL_API_TOKEN="$INTERNAL_TOKEN" nohup "$FRONTEND_DIR/node_modules/next/dist/bin/next" start -H 0.0.0.0 -p 3000 >>"$FRONTEND_LOG" 2>&1 &
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

if [[ "${COUNCIL_NO_BROWSER:-0}" != "1" ]]; then
  if [[ -n "$DESKTOP_TOKEN" ]]; then
    open "http://localhost:3000/pair#desktop:$DESKTOP_TOKEN"
  else
    open "http://localhost:3000"
  fi
fi
