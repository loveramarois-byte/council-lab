#!/bin/zsh

set -u
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council-bundled.pids"

if [[ -f "$PID_FILE" ]]; then
  while read -r service pid; do
    [[ "$pid" == <-> ]] || continue
    (( pid > 1 )) || continue
    /bin/kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  : > "$PID_FILE"
fi

/usr/bin/osascript -e 'display notification "Council 的本地服务已停止" with title "Council"' >/dev/null 2>&1 || true
