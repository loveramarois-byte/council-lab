#!/bin/zsh
set -euo pipefail

project_root="/Users/mac/Documents/Codex/2026-07-28/new-chat/council-lab-release-fix"
artifact_root="$project_root/artifacts"

if [[ ! -d "$artifact_root" ]]; then
  /usr/bin/osascript -e 'display alert "找不到 Council 构建目录" message "请确认项目目录仍位于 Documents/Codex 下。"'
  exit 1
fi

latest_app=""
latest_sort_key=""

while IFS= read -r -d '' app_path; do
  plist="$app_path/Contents/Info.plist"
  version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist" 2>/dev/null || true)
  [[ -n "$version" ]] || continue

  IFS=. read -r major minor patch _ <<< "$version"
  major=${major:-0}
  minor=${minor:-0}
  patch=${patch:-0}
  modified=$(/usr/bin/stat -f '%m' "$app_path" 2>/dev/null || printf '0')
  sort_key=$(printf '%010d.%010d.%010d.%020d' "$major" "$minor" "$patch" "$modified")

  if [[ -z "$latest_sort_key" || "$sort_key" > "$latest_sort_key" ]]; then
    latest_sort_key="$sort_key"
    latest_app="$app_path"
  fi
done < <(/usr/bin/find "$artifact_root" -maxdepth 3 -type d -path '*/Council.app' -print0)

if [[ -z "$latest_app" ]]; then
  /usr/bin/osascript -e 'display alert "没有找到 Council 应用" message "请先构建一个 macOS 版本。"'
  exit 1
fi

if [[ "${1:-}" == "--print" ]]; then
  printf '%s\n' "$latest_app"
  exit 0
fi

latest_executable="$latest_app/Contents/MacOS/CouncilNative"
latest_build_id="$(/bin/cat "$latest_app/Contents/Resources/web-build-id.txt" 2>/dev/null || true)"
running_build_id="$(/usr/bin/curl -fsS --max-time 1 http://127.0.0.1:3000/mobile-access/health 2>/dev/null \
  | /usr/bin/plutil -extract web_build_id raw -o - - 2>/dev/null || true)"
old_native_pids=()
old_apps=()

while read -r pid command; do
  case "$command" in
    "$artifact_root"/*/Council.app/Contents/MacOS/CouncilNative)
      if [[ "$command" == "$latest_executable" && -n "$latest_build_id" && "$running_build_id" == "$latest_build_id" ]]; then
        /usr/bin/open "$latest_app"
        exit 0
      fi
      old_native_pids+=("$pid")
      old_apps+=("${command%/Contents/MacOS/CouncilNative}")
      ;;
  esac
done < <(/bin/ps -axo pid=,command=)

for old_app in "${old_apps[@]}"; do
  stop_script="$old_app/Contents/Resources/launcher/stop-council.sh"
  [[ -x "$stop_script" ]] && "$stop_script" >/dev/null 2>&1 || true
done

for pid in "${old_native_pids[@]}"; do
  /bin/kill -TERM "$pid" 2>/dev/null || true
done

for attempt in {1..30}; do
  still_running=0
  for pid in "${old_native_pids[@]}"; do
    if /bin/kill -0 "$pid" 2>/dev/null; then
      still_running=1
      break
    fi
  done
  (( still_running == 0 )) && break
  /bin/sleep 0.1
done

for pid in "${old_native_pids[@]}"; do
  /bin/kill -KILL "$pid" 2>/dev/null || true
done

for attempt in {1..10}; do
  if /usr/bin/open -n "$latest_app"; then
    exit 0
  fi
  /bin/sleep 0.3
done

/usr/bin/osascript -e 'display alert "Council 启动失败" message "旧版本已经退出，但最新版暂时无法打开。请稍后重试。"'
exit 1
