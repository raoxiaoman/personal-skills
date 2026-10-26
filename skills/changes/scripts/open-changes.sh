#!/bin/bash
set -euo pipefail
if [[ $# -ne 1 || ! -d "$1" ]]; then
  printf '用法：open-changes.sh <工作区目录>\n' >&2
  exit 2
fi
root=$(git -C "$1" rev-parse --show-toplevel) || exit 2
command -v zed >/dev/null || { printf '未找到 zed 命令。\n' >&2; exit 1; }
printf '查看工作区改动：%s\n' "$root"
# 不强制复用其他项目的窗口，交由 Zed 匹配已有工作区。
zed "$root"
if /usr/bin/osascript <<'APPLESCRIPT'
tell application "Zed" to activate
tell application "System Events"
    repeat 20 times
        if exists process "Zed" then
            if frontmost of process "Zed" then exit repeat
        end if
        delay 0.1
    end repeat
    if not (exists process "Zed") then error "Zed 未启动"
    if not (frontmost of process "Zed") then error "Zed 未获得焦点"
    tell process "Zed"
        keystroke "g" using control down
        delay 0.2
        keystroke "d"
    end tell
end tell
APPLESCRIPT
then
  printf '已发送 Project Diff 按键；请在 Zed 确认视图及工作区。\n'
else
  printf '未能自动触发 Project Diff。在目标 Zed 窗口按 Ctrl+G，再按 D；或从命令面板执行 git: diff。\n' >&2
fi
