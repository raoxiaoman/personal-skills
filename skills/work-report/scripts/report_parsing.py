#!/usr/bin/env python3
"""日报归档的共用解析。

日期格式跨年不同，这是最容易踩的坑：

    2022–2025:  2025.12月31日   /  2025.11.28
    2026 起:    2026年9月21日

历史上 summarize_reports / generate_monthly_report / generate_review_2026 各自
硬编码过日期正则，格式一变就整体失效（2026 年全部解析成 0 条）。新增脚本请统一
从这里导入，不要再自己写正则。
"""

import datetime as _dt
import re

DATE_FORMATS = (
    # 2026 起：2026年9月21日
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
    # 2022–2025：2025.12月31日
    r"(20\d{2})\.\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
    # 2022–2025：2025.11.28
    r"(20\d{2})\.(\d{1,2})\.(\d{1,2})",
)

# 一整行就是一个日期（可带前导 # 与 BOM），用于切分日报条目
DATE_LINE = re.compile(
    r"^#?\s*(?:"
    r"(20\d{2})\s*(?:年|[.\s])\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"  # 2026年9月21日 / 2025.12月31日
    r"|"
    r"(20\d{2})\.(\d{1,2})\.(\d{1,2})"                              # 2025.11.28
    r")\s*$"
)

_DEV_HEADER = re.compile(r"^#?开发")

# 同一项目的不同写法归一到规范名。Maker 是 VideoGuru 的旧称，2026 年起两者混用；
# 各年从未在同一天共现，合并安全。
PROJECT_ALIASES = {
    "maker": "VideoGuru",
    "videoguru": "VideoGuru",
    "youcut": "YouCut",
    "utool": "Utool",
    "captune": "Captune",
}

# 项目名里混入的制表符/多余空白（如 "Ma\tker"）
_PROJECT_WHITESPACE = re.compile(r"\s+")


def normalize_project(name):
    """把项目名归一到规范写法。"""
    cleaned = _PROJECT_WHITESPACE.sub("", name.strip().rstrip("。.，,、：:；;！!？?"))
    return PROJECT_ALIASES.get(cleaned.lower(), cleaned)


def _to_date(groups):
    values = [g for g in groups if g is not None]
    if len(values) != 3:
        return None
    try:
        return _dt.date(*map(int, values))
    except ValueError:
        return None


def extract_date(text):
    """从一段文本里找出第一个合法日期，找不到返回 None。"""
    for pattern in DATE_FORMATS:
        for match in re.finditer(pattern, text):
            date = _to_date(match.groups())
            if date:
                return date
    return None


def is_date_line(line):
    """判断整行是否只是一个日期。"""
    stripped = line.strip().lstrip("﻿").lstrip("#").strip()
    match = DATE_LINE.match(stripped)
    return bool(match and _to_date(match.groups()))


def split_entries(text, marker="## 日报明细"):
    """把归档文件切成 (头部, 日报条目列表)。

    以「日期行」为锚点切分，而不是按 `---` 分隔符 —— 历史归档里有个别记录缺
    `---` 或 `#开发` 头，按分隔符切会少算天数。marker 为 None 时切整段文本。
    """
    body = text if marker is None or marker not in text else text[text.index(marker) + len(marker):]
    lines = body.split("\n")
    starts = []
    for i, line in enumerate(lines):
        if not is_date_line(line):
            continue
        prev = lines[i - 1].strip().lstrip("﻿") if i > 0 else ""
        starts.append(i - 1 if _DEV_HEADER.match(prev) else i)

    entries = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = "\n".join(lines[start:end])
        chunk = re.sub(r"(?:\n\s*-{3,}\s*)+$", "", chunk).strip("\n")
        if chunk and extract_date(chunk):
            entries.append(chunk)
    return entries


def parse_entry(entry, skip_plan=True):
    """解析单条日报，返回 {date, projects}。

    skip_plan=True 时忽略「下个工作日」之后的内容 —— 那是计划，不是已完成的工作。
    """
    date = None
    projects = {}
    current = None
    in_plan = False

    for raw in entry.split("\n"):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("---"):
            continue
        if date is None and is_date_line(line):
            date = extract_date(line)
            continue
        title = re.sub(r"^#{1,6}\s*", "", line).strip()
        if skip_plan and title.startswith("下个工作日"):
            in_plan = True
            continue
        # 计划段一旦开始，后续项目标题也不能重新开启工作采集。
        if in_plan:
            continue
        header = re.match(r"^#{1,6}\s*([^#].*?)\s*$", line)
        if header:
            # 历史日报里出现过 `#Maker。` / `#Ma\tker` 这类标题，统一归一后再判项目名，
            # 否则会多出一个脏项目名、并把该项算漏。
            name = normalize_project(header.group(1))
            current = None if name.lower() in ("开发", "android", "開発") else name
            continue
        if in_plan or current is None:
            continue
        item = re.match(r"^\d+[\.、]\s*(.+)$", line)
        if item:
            projects.setdefault(current, []).append(item.group(1).strip())
    return {"date": date, "projects": projects}


def load_year_file(path, year=None):
    """读取归档文件，返回解析后的条目列表。"""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    entries = [parse_entry(e) for e in split_entries(text)]
    entries = [e for e in entries if e["date"]]
    if year is not None:
        entries = [e for e in entries if e["date"].year == year]
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries