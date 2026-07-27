#!/bin/zsh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${COUNCIL_LOG_DIR:-$HOME/Library/Logs/Council}"
PID_FILE="$LOG_DIR/council.pids"

if [[ -f "$PID_FILE" ]]; then
  while read -r service pid; do
    [[ "$pid" == <-> ]] || continue
    (( pid > 1 )) || continue
    kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  : > "$PID_FILE"
fi

for port in 8001 3000; do
  for pid in $(lsof -tiTCP:$port -sTCP:LISTEN 2>/dev/null); do
    [[ "$pid" == <-> ]] || continue
    (( pid > 1 )) || continue
    process_cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
    process_command=$(ps -p "$pid" -o command= 2>/dev/null)
    if [[ "$process_cwd" == "$PROJECT_DIR"* || "$process_command" == *"$PROJECT_DIR"* ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
done

osascript -e 'display notification "Council 的本地服务已停止" with title "Council"' >/dev/null 2>&1 || true
