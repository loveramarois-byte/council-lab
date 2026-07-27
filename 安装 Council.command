#!/bin/zsh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

clear
echo "正在安装 Council，请稍候..."
echo

if "$SCRIPT_DIR/setup.sh"; then
  echo
  echo "安装成功，正在打开 Council。"
  open "$HOME/Desktop/Council.app"
else
  echo
  echo "安装失败。请按任意键关闭窗口。"
  read -k 1
  exit 1
fi
