#!/bin/zsh

set -u

NEW_APP="${1:-}"
TARGET_APP="${2:-}"
STOPPER="${3:-}"
LOG_FILE="${4:-$HOME/Library/Logs/Council/update.log}"
RESULT_FILE="${5:-$HOME/Library/Application Support/Council/data/updates/last-result.json}"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$RESULT_FILE")"
exec >>"$LOG_FILE" 2>&1

write_result() {
  local result_status="$1"
  local message="$2"
  /usr/bin/printf '{"status":"%s","message":"%s"}\n' "$result_status" "${message//\"/\\\"}" > "$RESULT_FILE"
}

restart_target() {
  [[ "${COUNCIL_UPDATE_NO_RESTART:-0}" == "1" ]] && return 0
  [[ -d "$TARGET_APP" ]] && /usr/bin/open "$TARGET_APP" >/dev/null 2>&1 || true
}

PATHS_OVERLAP=0
if [[ "$NEW_APP" == "$TARGET_APP" || "$NEW_APP" == "$TARGET_APP"/* || "$TARGET_APP" == "$NEW_APP"/* ]]; then
  PATHS_OVERLAP=1
fi

if [[ ! -d "$NEW_APP/Contents/Resources" || ! -x "$STOPPER" || "$TARGET_APP:t" != "Council.app" || "$TARGET_APP" == "/Council.app" || "$PATHS_OVERLAP" == "1" ]]; then
  write_result error "更新路径校验失败。"
  exit 1
fi

if ! /usr/bin/codesign --verify --deep --strict "$NEW_APP"; then
  write_result error "新版 Council.app 签名结构校验失败，当前版本未被修改。"
  exit 1
fi

/bin/sleep 1
/bin/zsh "$STOPPER" >/dev/null 2>&1 || true
/bin/sleep 1

TARGET_PARENT="$TARGET_APP:h"
BACKUP_APP="$TARGET_PARENT/.Council.backup.$$"

replace_app() {
  /bin/mv "$TARGET_APP" "$BACKUP_APP" || return 1
  if /usr/bin/ditto "$NEW_APP" "$TARGET_APP"; then
    /bin/rm -rf "$BACKUP_APP"
    return 0
  fi
  /bin/rm -rf "$TARGET_APP"
  /bin/mv "$BACKUP_APP" "$TARGET_APP"
  return 1
}

if [[ -w "$TARGET_PARENT" ]]; then
  replace_app || {
    write_result error "替换 Council.app 失败，已恢复旧版本。"
    restart_target
    exit 1
  }
else
  /usr/bin/osascript - "$NEW_APP" "$TARGET_APP" "$BACKUP_APP" <<'APPLESCRIPT'
on run argv
  set newApp to item 1 of argv
  set targetApp to item 2 of argv
  set backupApp to item 3 of argv
  set commandBody to "set -e; /bin/mv " & quoted form of targetApp & " " & quoted form of backupApp & "; if /usr/bin/ditto " & quoted form of newApp & " " & quoted form of targetApp & "; then /bin/rm -rf " & quoted form of backupApp & "; else /bin/rm -rf " & quoted form of targetApp & "; /bin/mv " & quoted form of backupApp & " " & quoted form of targetApp & "; exit 1; fi"
  do shell script "/bin/zsh -c " & quoted form of commandBody with administrator privileges
end run
APPLESCRIPT
  if [[ $? -ne 0 ]]; then
    write_result error "未能获得替换应用所需的系统权限，仍保留旧版本。"
    restart_target
    exit 1
  fi
fi

write_result success "Council 已更新，正在重新打开。"
restart_target
