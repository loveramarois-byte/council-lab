#!/bin/zsh

set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council-bundled.pids"

stop_process() {
  local service="$1"
  local pid="$2"
  local command_line
  local process_cwd
  local attempt

  [[ "$pid" == <-> ]] || return 0
  (( pid > 1 )) || return 0
  command_line="$(/bin/ps -p "$pid" -o command= 2>/dev/null || true)"
  if [[ "$command_line" != *"$RESOURCES_DIR"* ]]; then
    [[ "$service" == "frontend" ]] || return 0
    process_cwd="$(/usr/sbin/lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | /usr/bin/awk '/^n/ {sub(/^n/, ""); print; exit}')"
    [[ "$process_cwd" == "$RESOURCES_DIR/web" ]] || return 0
  fi

  /bin/kill "$pid" 2>/dev/null || true
  for attempt in {1..30}; do
    /bin/kill -0 "$pid" 2>/dev/null || return 0
    /bin/sleep 0.1
  done

  /bin/kill -KILL "$pid" 2>/dev/null || true
}

if [[ -f "$PID_FILE" ]]; then
  while read -r service pid; do
    stop_process "$service" "$pid"
  done < "$PID_FILE"
  : > "$PID_FILE"
fi

/usr/bin/osascript -e 'display notification "Council 的本地服务已停止" with title "Council"' >/dev/null 2>&1 || true
