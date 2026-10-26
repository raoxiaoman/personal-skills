#!/bin/bash
set -euo pipefail
if [[ $# -ne 1 ]]; then
  printf '用法：open-changes.sh <工作区目录>\n' >&2
  exit 2
fi
target=$1
case "$target" in
  '~') target=$HOME ;;
  '~/'*) target="$HOME/${target:2}" ;;
esac
if [[ ! -d "$target" ]]; then
  printf '工作区目录不存在或不可访问：%s\n请核对实际 worktree 路径；不会改开主仓库。\n' "$target" >&2
  exit 2
fi
if ! root=$(git -C "$target" rev-parse --show-toplevel 2>/dev/null); then
  printf '目标不是有效 Git 工作区：%s\n' "$target" >&2
  exit 2
fi
command -v zed >/dev/null || { printf '未找到 zed 命令。\n' >&2; exit 1; }
printf '查看工作区改动：%s\n' "$root"
# 不强制复用其他项目的窗口，交由 Zed 匹配已有工作区。
zed "$root"
printf '已在 Zed 打开工作区；请手动选择 Git diff。\n'
