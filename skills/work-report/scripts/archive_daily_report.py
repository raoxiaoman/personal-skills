#!/usr/bin/env python3
"""把一天的日报归档进 reports/{year}.md，并重算年度/月度统计、关键里程碑与索引。

用法:
  # 先看会改成什么样（不写任何文件）
  python3 archive_daily_report.py --date 2026-09-22 --file /tmp/draft.md --dry-run

  # 确认后写入
  python3 archive_daily_report.py --date 2026-09-22 --file /tmp/draft.md

草稿文件就是当天日报正文，从「#开发」和日期行开始：

  #开发
  2026年9月22日

  #VideoGuru
  1. 修复 xxx（abc1234）

  下个工作日
  1. 继续 yyy

细则:
  - 同一日期重复归档会直接报错退出，不会写坏文件。
  - 只重写文件头部统计区，日报明细逐条原样保留（不做行尾/分隔符归一）。
  - 统计口径: 「天」= 该项目当天出现；「项」= 该项目当天编号条目数；不统计「下个工作日」。
"""

import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_parsing

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(SKILL_DIR, "reports")

DETAIL_MARKER = "## 日报明细"
MILESTONE_KEYWORDS = ("完成", "发布", "上线", "提测", "重构")
SEPARATOR = "\n---\n"


def parse_date(text):
    """返回 (year, month, day) 或 None。日期格式兼容见 report_parsing。"""
    date = report_parsing.extract_date(text)
    return (date.year, date.month, date.day) if date else None


def parse_entry(text):
    """解析一条日报，返回 {date, projects}。"""
    parsed = report_parsing.parse_entry(text)
    date = parsed["date"]
    return {
        "date": (date.year, date.month, date.day) if date else None,
        "projects": parsed["projects"],
    }


def split_file(content):
    """切成 (头部区, 明细区)。头部区到 ## 日报明细 之前为止。"""
    idx = content.index(DETAIL_MARKER)
    return content[:idx], content[idx:]


def list_entries(region):
    """从明细区取出每条日报的原文（不重写行尾与分隔符）。

    切分口径（含历史缺失 `---` / `#开发` 头的兜底）统一由 report_parsing 负责。
    """
    return report_parsing.split_entries(region, marker=DETAIL_MARKER)


def stats(year, entries):
    parsed = []
    for e in entries:
        p = parse_entry(e)
        if p["date"] and p["date"][0] == year:
            parsed.append(p)
    parsed.sort(key=lambda p: p["date"], reverse=True)

    days, items = defaultdict(int), defaultdict(int)
    for p in parsed:
        for name, its in p["projects"].items():
            days[name] += 1
            items[name] += len(its)

    milestones = defaultdict(list)
    for p in parsed:
        _, m, d = p["date"]
        for name, its in p["projects"].items():
            for it in its:
                if any(k in it for k in MILESTONE_KEYWORDS):
                    milestones[m].append((d, name, it))
    return parsed, days, items, milestones


def render_header(year, parsed, days, items, milestones, cap):
    order = sorted(days, key=lambda x: (-days[x], x))
    nodes = sum(len(v) for v in milestones.values())

    out = [f"# {year} 年开发日报", "", "## 📊 年度概览", "", f"- **工作日**: {len(parsed)} 天"]
    if order:
        out.append("- **项目**: " + "、".join(f"{p}({days[p]}天/{items[p]}项)" for p in order))
    out.append(f"- **关键节点**: 共 {nodes} 个完成/发布/上线/提测/重构事项")
    out += ["", "## 各月汇总", ""]

    by_month = defaultdict(list)
    for p in parsed:
        by_month[p["date"][1]].append(p)
    for m in sorted(by_month, reverse=True):
        md, mi = defaultdict(int), defaultdict(int)
        for p in by_month[m]:
            for name, its in p["projects"].items():
                md[name] += 1
                mi[name] += len(its)
        top = sorted(md, key=lambda x: (-md[x], x))[:5]
        out.append(f"### {m}月")
        out.append(f"- 工作日: {len(by_month[m])} 天 | 工作项: {sum(mi.values())} 项")
        if top:
            out.append("- 涉及项目: " + "、".join(f"{p}({md[p]}天)" for p in top))
        out.append("")

    out += ["## 关键里程碑", ""]
    out.append(f"> 取各月中含「完成/发布/上线/提测/重构」的事项，每月最多列 {cap} 条（括号内为该月全部条数）。")
    dropped = []
    for m in sorted(milestones, reverse=True):
        ms = milestones[m]
        out += ["", f"**{m}月** ({len(ms)} 项)"]
        for d, name, it in ms[:cap]:
            out.append(f"  - {d}日: [{name}] {it}")
        dropped += [f"{m}月{d}日 [{name}] {it}" for d, name, it in ms[cap:]]
    out += ["", "---", ""]
    return "\n".join(out), dropped


def render_index():
    rows = []
    for name in sorted(os.listdir(REPORTS_DIR)):
        if not re.match(r"^\d{4}\.md$", name):
            continue
        year = int(name[:4])
        with open(os.path.join(REPORTS_DIR, name), encoding="utf-8") as f:
            _, region = split_file(f.read())
        parsed, days, _, _ = stats(year, list_entries(region))
        top = sorted(days, key=lambda x: (-days[x], x))[:3]
        rows.append((year, f"- [{year}]({name}) — {len(parsed)} 天 | "
                           + "、".join(f"{p}({days[p]}天)" for p in top)))
    lines = ["# 开发日报索引", "", "按年份整理的工作日报。", ""]
    lines += [r for _, r in sorted(rows, reverse=True)]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="归档日期 YYYY-MM-DD")
    ap.add_argument("--file", dest="src", required=True, help="日报正文文件")
    ap.add_argument("--dry-run", action="store_true", help="只报告结果，不写文件")
    ap.add_argument("--milestone-cap", type=int, default=8, help="每月关键里程碑最多展示条数")
    args = ap.parse_args()

    y, m, d = (int(x) for x in args.date.split("-"))
    with open(args.src, encoding="utf-8") as f:
        entry = f.read().strip("\n")

    if parse_date(entry) != (y, m, d):
        sys.exit(f"错误: 草稿日期 {parse_date(entry)} 与 --date {args.date} 不一致")
    if "下个工作日" not in entry:
        print("警告: 草稿里没有「下个工作日」段落")

    path = os.path.join(REPORTS_DIR, f"{y}.md")
    if not os.path.exists(path):
        sys.exit(f"错误: 找不到 {path}")
    with open(path, encoding="utf-8") as f:
        content = f.read()

    _, region = split_file(content)
    for e in list_entries(region):
        if parse_date(e) == (y, m, d):
            sys.exit(f"错误: {args.date} 已归档，未写入任何内容")

    # 明细区原文原样保留，只在最前面插入新条目
    new_region = DETAIL_MARKER + "\n" + entry + "\n" + SEPARATOR + region[len(DETAIL_MARKER):].lstrip("\n")
    entries = list_entries(new_region)
    parsed, days, items, milestones = stats(y, entries)
    header, dropped = render_header(y, parsed, days, items, milestones, args.milestone_cap)

    total = sum(len(p["projects"][k]) for p in parsed for k in p["projects"])
    if args.dry_run:
        print(f"[dry-run] {args.date}: 将插入 1 条记录，明细共 {len(entries)} 条（未写文件）")
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + new_region)
        with open(os.path.join(REPORTS_DIR, "README.md"), "w", encoding="utf-8") as f:
            f.write(render_index())
        print(f"已归档 {args.date} -> {path}")
    print(f"{y} 年: {len(parsed)} 天 / {total} 项 | 项目天数: "
          + str(dict(sorted(days.items(), key=lambda x: -x[1]))))
    if dropped:
        print(f"关键里程碑超出 {args.milestone_cap} 条未展示（明细中仍完整保留）")


if __name__ == "__main__":
    main()
