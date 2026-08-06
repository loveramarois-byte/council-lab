#!/bin/zsh

set -u
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
RESOURCES_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
BACKEND_EXE="$RESOURCES_DIR/backend/council-backend/council-backend"
NODE_EXE="$RESOURCES_DIR/runtime/node"
WEB_DIR="$RESOURCES_DIR/web"
WEB_BUILD_ID_FILE="$WEB_DIR/.next-release/BUILD_ID"
APP_ROOT="$(cd "$RESOURCES_DIR/../.." && pwd -P)"
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council-bundled.pids"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
TOKEN_FILE="$LOG_DIR/mobile-access.token"
DESKTOP_TOKEN_FILE="$LOG_DIR/desktop-access.token"
INTERNAL_TOKEN_FILE="$LOG_DIR/backend-access.token"
STARTUP_LOCK_FILE="$LOG_DIR/startup.lock"

mkdir -p "$LOG_DIR"
export COUNCIL_PACKAGED=1
export COUNCIL_INSTALL_ROOT="$APP_ROOT"
export COUNCIL_VERSION="$(/usr/bin/tr -d '[:space:]' < "$RESOURCES_DIR/VERSION")"
export COUNCIL_RUNTIME_ID="macos:$(/usr/bin/printf '%s\0%s' "$APP_ROOT" "$COUNCIL_VERSION" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print substr($1, 1, 24)}')"

show_error() {
  /usr/bin/osascript -e "display dialog \"$1\" buttons {\"好\"} with title \"Council 无法启动\"" >/dev/null 2>&1 || true
}

release_startup_lock() {
  local owner=""
  [[ -f "$STARTUP_LOCK_FILE" ]] && owner="$(/usr/bin/tr -d '[:space:]' < "$STARTUP_LOCK_FILE")"
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
  show_error "Council 正在由另一个窗口启动，请稍后重试。"
  exit 1
fi
trap release_startup_lock EXIT

/usr/bin/touch "$PID_FILE"

service_is_current() {
  local url="$1"
  local service="$2"
  local expected_web_build_id="${3:-}"
  local response
  response="$(/usr/bin/curl -fsS --max-time 2 "$url" 2>/dev/null || true)"
  [[ "$response" == *"\"service\":\"$service\""* \
    && "$response" == *"\"runtime_id\":\"$COUNCIL_RUNTIME_ID\""* \
    && "$response" == *"\"internal_api_id\":\"$INTERNAL_API_ID\""* ]] || return 1
  [[ -z "$expected_web_build_id" \
    || "$response" == *"\"web_build_id\":\"$expected_web_build_id\""* ]]
}

backend_is_current() {
  service_is_current "http://127.0.0.1:8001/api/health" "council-lab"
}

frontend_is_current() {
  local response
  local web_build_id="$COUNCIL_WEB_BUILD_ID"
  response="$(/usr/bin/curl -fsSi --max-time 2 "http://127.0.0.1:3000/mobile-access/health" 2>/dev/null || true)"
  [[ "$response" == *'"service":"council-mobile-access"'* \
    && "$response" == *"\"runtime_id\":\"$COUNCIL_RUNTIME_ID\""* \
    && "$response" == *"\"web_build_id\":\"$web_build_id\""* \
    && "$response" == *"\"internal_api_id\":\"$INTERNAL_API_ID\""* \
    && "${response:l}" == *"x-council-desktop-token-id: $DESKTOP_TOKEN_ID"* ]]
}

port_is_used() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

process_is_council() {
  local pid="$1"
  local service="$2"
  local process_cwd
  local process_command
  local process_executable
  process_cwd="$(/usr/sbin/lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | /usr/bin/sed -n 's/^n//p' | /usr/bin/head -1)"
  process_command="$(/bin/ps -p "$pid" -o command= 2>/dev/null || true)"
  process_executable="$(/usr/sbin/lsof -a -p "$pid" -d txt -Fn 2>/dev/null | /usr/bin/sed -n 's/^n//p' | /usr/bin/head -1)"
  if [[ "$service" == "council-lab" ]]; then
    [[ "$process_executable" == */Contents/Resources/backend/council-backend/council-backend ]] && return 0
    [[ "$process_cwd" == */backend && -f "$process_cwd/app/main.py" && "$process_command" == *"uvicorn app.main:app"* ]] && return 0
  elif [[ "$service" == "council-mobile-access" ]]; then
    [[ "$process_executable" == */Contents/Resources/runtime/node && "$process_cwd" == */Contents/Resources/web && -f "$process_cwd/server.js" ]] && return 0
    [[ "$process_cwd" == */frontend && -f "$process_cwd/package.json" && -f "$process_cwd/next.config.ts" && -f "$process_cwd/app/layout.tsx" ]] \
      && /usr/bin/grep -Eq '"name"[[:space:]]*:[[:space:]]*"council-lab-web"' "$process_cwd/package.json" \
      && return 0
  fi
  return 1
}

stop_existing_council_service() {
  local port="$1"
  local url="$2"
  local service="$3"
  local response
  local listeners_before
  local listeners_after
  local pid
  local attempt
  listeners_before=" $(/usr/sbin/lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | /usr/bin/tr '\n' ' ') "
  response="$(/usr/bin/curl -fsS --max-time 2 "$url" 2>/dev/null || true)"
  [[ "$response" == *"\"service\":\"$service\""* ]] || return 1
  listeners_after=" $(/usr/sbin/lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | /usr/bin/tr '\n' ' ') "
  for pid in $=listeners_after; do
    [[ "$pid" == <-> ]] || continue
    (( pid > 1 )) || continue
    [[ "$listeners_before" == *" $pid "* ]] || continue
    process_is_council "$pid" "$service" || continue
    /bin/kill "$pid" 2>/dev/null || true
  done
  for attempt in {1..30}; do
    port_is_used "$port" || return 0
    /bin/sleep 0.1
  done
  for pid in $(/usr/sbin/lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
    [[ "$pid" == <-> ]] || continue
    (( pid > 1 )) || continue
    [[ "$listeners_before" == *" $pid "* ]] || continue
    process_is_council "$pid" "$service" || continue
    /bin/kill -KILL "$pid" 2>/dev/null || true
  done
  ! port_is_used "$port"
}

wait_for_service() {
  local checker="$1"
  local attempts=0
  while (( attempts < 60 )); do
    "$checker" && return 0
    /bin/sleep 0.25
    attempts=$((attempts + 1))
  done
  return 1
}

record_pid() {
  local service="$1"
  local pid="$2"
  local temp_file="${PID_FILE}.tmp.$$"
  /usr/bin/awk -v target="$service" '$1 != target' "$PID_FILE" > "$temp_file" 2>/dev/null || true
  echo "$service $pid" >> "$temp_file"
  /bin/mv "$temp_file" "$PID_FILE"
}

if [[ ! -x "$BACKEND_EXE" || ! -x "$NODE_EXE" || ! -f "$WEB_DIR/server.js" || ! -f "$WEB_BUILD_ID_FILE" ]]; then
  show_error "安装包不完整，请重新下载并解压 Council。"
  exit 1
fi

export COUNCIL_WEB_BUILD_ID="$(/usr/bin/tr -d '[:space:]' < "$WEB_BUILD_ID_FILE")"

umask 077
INTERNAL_TOKEN=""
if [[ -f "$INTERNAL_TOKEN_FILE" ]]; then
  INTERNAL_TOKEN="$(/usr/bin/tr -d '[:space:]' < "$INTERNAL_TOKEN_FILE")"
fi
if (( ${#INTERNAL_TOKEN} < 32 )); then
  INTERNAL_TOKEN="$(/usr/bin/openssl rand -hex 24)"
  printf '%s\n' "$INTERNAL_TOKEN" > "$INTERNAL_TOKEN_FILE"
fi
/bin/chmod 600 "$INTERNAL_TOKEN_FILE"
INTERNAL_API_ID="$(/usr/bin/printf '%s' "$INTERNAL_TOKEN" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print substr($1, 1, 16)}')"

if ! backend_is_current; then
  if port_is_used 8001; then
    if ! stop_existing_council_service 8001 "http://127.0.0.1:8001/api/health" "council-lab"; then
      show_error "端口 8001 已被其他程序占用，请先关闭该程序。"
      exit 1
    fi
  fi
  COUNCIL_INTERNAL_API_TOKEN="$INTERNAL_TOKEN" /usr/bin/nohup "$BACKEND_EXE" >>"$BACKEND_LOG" 2>&1 &
  backend_pid=$!
  record_pid backend "$backend_pid"
  if ! wait_for_service backend_is_current; then
    show_error "后端启动失败，请查看 ~/Library/Logs/Council/backend.log。"
    exit 1
  fi
fi

REMOTE_TOKEN=""
DESKTOP_TOKEN=""
DESKTOP_TOKEN_ID=""
if [[ -f "$TOKEN_FILE" && -f "$DESKTOP_TOKEN_FILE" ]]; then
  REMOTE_TOKEN="$(/usr/bin/tr -d '[:space:]' < "$TOKEN_FILE")"
  DESKTOP_TOKEN="$(/usr/bin/tr -d '[:space:]' < "$DESKTOP_TOKEN_FILE")"
  if (( ${#DESKTOP_TOKEN} >= 32 )); then
    DESKTOP_TOKEN_ID="$(/usr/bin/printf '%s' "$DESKTOP_TOKEN" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print substr($1, 1, 16)}')"
  fi
fi

if ! frontend_is_current; then
  if port_is_used 3000; then
    if ! stop_existing_council_service 3000 "http://127.0.0.1:3000/mobile-access/health" "council-mobile-access"; then
      show_error "端口 3000 已被其他程序占用，请先关闭该程序。"
      exit 1
    fi
  fi
  REMOTE_TOKEN="$(/usr/bin/openssl rand -hex 24)"
  DESKTOP_TOKEN="$(/usr/bin/openssl rand -hex 24)"
  DESKTOP_TOKEN_ID="$(/usr/bin/printf '%s' "$DESKTOP_TOKEN" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print substr($1, 1, 16)}')"
  printf '%s\n' "$REMOTE_TOKEN" > "$TOKEN_FILE"
  printf '%s\n' "$DESKTOP_TOKEN" > "$DESKTOP_TOKEN_FILE"
  pushd "$WEB_DIR" >/dev/null
  HOSTNAME=0.0.0.0 PORT=3000 NODE_ENV=production COUNCIL_REMOTE_TOKEN="$REMOTE_TOKEN" COUNCIL_DESKTOP_TOKEN="$DESKTOP_TOKEN" COUNCIL_INTERNAL_API_TOKEN="$INTERNAL_TOKEN" \
    /usr/bin/nohup "$NODE_EXE" "$WEB_DIR/server.js" >>"$FRONTEND_LOG" 2>&1 &
  frontend_pid=$!
  popd >/dev/null
  record_pid frontend "$frontend_pid"
  if ! wait_for_service frontend_is_current; then
    show_error "网页启动失败，请查看 ~/Library/Logs/Council/frontend.log。"
    exit 1
  fi
fi

if [[ "${COUNCIL_NO_BROWSER:-0}" != "1" ]]; then
  if [[ -n "$DESKTOP_TOKEN" ]]; then
    /usr/bin/open "http://localhost:3000/pair#desktop:$DESKTOP_TOKEN"
  else
    /usr/bin/open "http://localhost:3000"
  fi
fi
