#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

DEFAULT_REPOS = [
    "/Users/raohui/code/work/YouCut/YouCutAndroid",
    "/Users/raohui/code/work/videoGuru/VideoGuruAndroid",
    "/Users/raohui/code/work/yuv-Feature",
    "/Users/raohui/code/work/Captune",
    "/Users/raohui/code/work/utool",
]

# 只认「用户手打的提问」。Claude 侧记录里绝大多数行是技能清单、系统提示、
# 工具结果回灌，靠关键词筛会把它们一起捞进来，输出能到上百 KB。
PROMPT_MARKER = '"promptSource":"typed"'
PROMPT_MAX_BYTES = 8000     # 单行超过这么多字节的，基本是粘贴进来的文档/日志
PROMPT_MAX_CHARS = 1200     # 解析后正文再卡一道
PROMPT_MAX_RECORDS = 40     # 上限，避免整天泡在对话里的日子把输出撑回原样
PROMPT_SHORT_CHARS = 8      # 短于这个长度的提问，除非带具体标识，一律视为对话噪音

# 短指令里如果出现下面任一形态，说明它真的指向某件事，保留。
# 例：「改 #199A_4」「PIP 也要改」「重启 adb」
PROMPT_IDENTIFIER = re.compile(
    r"#[A-Za-z0-9_]+"                       # bug / 需求编号
    r"|[A-Za-z0-9]+_[A-Za-z0-9]+"           # AudioDenoiseFragment 这类下划线标识
    r"|[\w./-]+\.(?:kt|java|xml|md|sh|py|json|so)"   # 文件名
    r"|[A-Za-z]{3,}"                        # 长度 3 以上的英文词
)


NOISE_PREFIXES = (
    "pack:", "merge", "Merge", "revert", "Revert"
)


def run(cmd, cwd=None):
    try:
        return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def infer_author(repo):
    name = run(["git", "config", "user.name"], cwd=repo)
    return name or "raohui"


def discover_worktrees(repo):
    """Return the main checkout and registered worktrees for a repository."""
    repo_path = Path(repo).expanduser()
    if not repo_path.exists():
        return []
    output = run(["git", "worktree", "list", "--porcelain"], cwd=str(repo_path))
    paths = []
    for line in output.splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line.removeprefix("worktree ").strip()).expanduser()
        if path.exists() and path not in paths:
            paths.append(path)
    if repo_path not in paths:
        paths.insert(0, repo_path)
    return paths


def normalize_subject(subject):
    s = subject.strip()
    s = re.sub(r"^(fix:|feat:|chore:|refactor:|模版改版-修复-|模板改版-修复-|修复-)\s*", "", s, flags=re.I)
    s = re.sub(r"#?\d{4}[A-Z]?_\d+\s*", "", s)
    s = re.sub(r"#首页模版优化\s*", "首页模板优化", s)
    s = re.sub(r"\s+", " ", s).strip(" -，,。")
    return s


def repo_label(repo):
    p = Path(repo)
    parts = p.parts
    if "YouCutAndroid" in parts:
        return "YouCut"
    if "VideoGuruAndroid" in parts:
        return "VideoGuru"
    return p.name


def collect_git(repo, date, author=None):
    repo_path = Path(repo).expanduser()
    if not repo_path.exists():
        return []
    author = author or infer_author(str(repo_path))
    # 必须按「作者日期」筛，不能用 --since/--until —— 那两个开关比的是
    # committer date。本仓库大量提交的作者日期早于提交日期（改完隔天才提交，
    # 或 rebase 后重打），近 90 天 348 笔里有 32 笔如此。用 --since 查某天，
    # 会把前几天写的提交一起捞进来，日报里就会出现已经不是当天的工作。
    fmt = "%H%x1f%an%x1f%ad%x1f%s"
    out = run([
        "git", "log", f"--author={author}", "--since=1 year ago",
        f"--pretty=format:{fmt}", "--date=format:%Y-%m-%d %H:%M"
    ], cwd=str(repo_path))
    items = []
    for line in out.splitlines():
        cols = line.split("\x1f")
        if len(cols) != 4:
            continue
        h, an, when, subject = cols
        if not when.startswith(date):
            continue
        normalized = normalize_subject(subject)
        if not normalized or normalized.startswith(NOISE_PREFIXES):
            continue
        items.append({
            "repo": str(repo_path),
            "project": repo_label(str(repo_path)),
            "hash": h,
            "author": an,
            "time": when,
            "subject": subject,
            "summary": normalized,
        })
    return items


def to_local(timestamp):
    """把 JSONL 里的 UTC 时间戳转成本地时间，失败返回 None。"""
    if not timestamp:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone()


def collect_claude_records(date):
    """按日期取用户实际输入的提问，作为无提交工作的补充证据。

    旧实现按关键词在所有行里捞，输出 120 条原始 JSONL（约 99KB），
    其中技能清单和系统提示占了大半。这里改成只认 typed 提问标记，
    并就地解析成 {time, text}，顺带把 mtime 判断改成容错读取。
    """
    roots = [Path("/Users/raohui/.claude/projects")]
    records = []
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if dt.datetime.fromtimestamp(stat.st_mtime).date().isoformat() != date:
                continue
            try:
                handle = path.open(errors="ignore")
            except OSError:
                continue
            with handle:
                for line in handle:
                    if PROMPT_MARKER not in line or len(line) > PROMPT_MAX_BYTES:
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    # JSONL 里的时间戳是 UTC（形如 2026-09-21T02:08:12Z），
                    # 直接拿它跟本地日期比，会把本地 00:00-08:00 的提问
                    # 算到前一天去。统一转成本地时区再判断。
                    local = to_local(payload.get("timestamp"))
                    if local is None or local.date().isoformat() != date:
                        continue
                    content = payload.get("message", {}).get("content")
                    if not isinstance(content, str) or len(content) > PROMPT_MAX_CHARS:
                        continue
                    text = " ".join(content.split())
                    # 「继续」「提交把」「要」「1」这类推进话术占了短指令的绝大多数，
                    # 它们不指向任何具体工作，进日报只会变成噪声。
                    if len(text) <= PROMPT_SHORT_CHARS and not PROMPT_IDENTIFIER.search(text):
                        continue
                    if text in seen:
                        continue
                    seen.add(text)
                    records.append({
                        "time": local.strftime("%H:%M"),
                        "text": text,
                        "session": path.stem[:8],
                    })
    return sorted(records, key=lambda r: r["time"])[:PROMPT_MAX_RECORDS]


def dedupe(items):
    seen = set()
    result = []
    for item in items:
        key = re.sub(r"[\s，,。#_\-:：]+", "", item["summary"].lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description="Collect daily git and Claude work records")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--repo", action="append", dest="repos", help="Repo path, repeatable")
    parser.add_argument("--author", default="raohui")
    parser.add_argument("--include-claude", action="store_true")
    args = parser.parse_args()

    repos = args.repos or DEFAULT_REPOS
    checkout_paths = []
    for repo in repos:
        for checkout in discover_worktrees(repo):
            checkout_str = str(checkout)
            if checkout_str not in checkout_paths:
                checkout_paths.append(checkout_str)

    git_items = []
    for repo in checkout_paths:
        git_items.extend(collect_git(repo, args.date, args.author))
    git_items = dedupe(sorted(git_items, key=lambda x: x["time"]))

    # 只列出当天真的有提交的 worktree，其余 50 来个闲置 worktree 路径
    # 对写日报没有任何用，去掉能省掉一大截上下文。
    touched = {item["repo"] for item in git_items}
    data = {
        "date": args.date,
        "author": args.author,
        "repos": [p for p in checkout_paths if p in touched],
        "git_items": git_items,
        "claude_records": collect_claude_records(args.date) if args.include_claude else [],
    }
    print(json.dumps(data, ensure_ascii=False, indent=1, separators=(",", ": ")))


if __name__ == "__main__":
    main()
