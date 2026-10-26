#!/usr/bin/env python3
"""
Summarize daily reports by year, month, project, or custom requirements.
Reads from reports/{year}.md and outputs structured markdown summaries.
"""

import re
import os
import argparse
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_parsing

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(SKILL_DIR, "reports")


def list_available_years():
    """List all report files available."""
    files = []
    for f in os.listdir(REPORTS_DIR):
        m = re.match(r'(\d{4})\.md$', f)
        if m:
            files.append(int(m.group(1)))
    return sorted(files, reverse=True)


def parse_report_file(filepath):
    """解析归档文件，返回条目列表。

    日期识别、条目切分与「下个工作日」隔离统一走 report_parsing，不要再自己写正则。
    """
    entries = []
    for parsed in report_parsing.load_year_file(filepath):
        date = parsed["date"]
        entries.append({
            "date": (date.year, date.month, date.day),
            "date_str": f"{date.year}.{date.month}月{date.day}日",
            "projects": dict(parsed["projects"]),
        })
    return entries


def summarize_year(year, month=None, project_filter=None):
    """Generate a year summary."""
    filepath = os.path.join(REPORTS_DIR, f"{year}.md")
    if not os.path.exists(filepath):
        return f"错误：{year} 年的日报文件不存在。"

    entries = parse_report_file(filepath)

    # Filter by month
    if month:
        entries = [e for e in entries if e['date'][1] == month]
        if not entries:
            return f"错误：{year}年{month}月没有日报记录。"

    # Filter by project
    if project_filter:
        filtered = []
        for e in entries:
            projs = {k: v for k, v in e['projects'].items()
                     if k.lower() == project_filter.lower()}
            if projs:
                e['projects'] = projs
                filtered.append(e)
        entries = filtered
        if not entries:
            return f"错误：{year}年没有找到 [{project_filter}] 项目的日报。"

    # Count stats
    total_days = len(entries)
    project_days = defaultdict(int)
    project_items = defaultdict(int)
    all_items = []

    for e in entries:
        for proj, items in e['projects'].items():
            project_days[proj] += 1
            project_items[proj] += len(items)
            for item in items:
                all_items.append((e['date'], proj, item))

    # Count bugs
    bug_count = sum(1 for _, _, item in all_items
                    if re.search(r'bug|fix|修复|crash', item, re.IGNORECASE))

    # Count releases
    release_count = sum(1 for _, _, item in all_items
                        if re.search(r'发布|上线|提测', item))

    # Build output
    if month:
        title = f"{year}年{month}月 月度总结"
    else:
        title = f"{year}年 工作总结"

    lines = [f"# {title}\n"]

    # Stats
    lines.append("## 📊 数览\n")
    lines.append(f"- **工作日**: {total_days} 天")
    proj_str = "、".join(
        [f"{p}({project_days[p]}天/{project_items[p]}项)"
         for p in sorted(project_days.keys(), key=lambda x: -project_days[x])]
    )
    lines.append(f"- **项目**: {proj_str}")
    lines.append(f"- **Bug 修复**: ~{bug_count} 处")
    lines.append(f"- **版本发布/提测**: ~{release_count} 次\n")

    # Monthly or weekly breakdown
    if month:
        # Show weekly breakdown by day
        lines.append("### 逐日概况\n")
        for e in sorted(entries, key=lambda x: x['date']):
            proj_items_str = "、".join(
                [f"{p}({len(items)}项)" for p, items in e['projects'].items()]
            )
            lines.append(f"- **{e['date_str']}**: {proj_items_str}")
        lines.append("")
    else:
        # Monthly breakdown
        lines.append("### 📈 月度节奏\n")
        entries_by_month = defaultdict(list)
        for e in entries:
            entries_by_month[e['date'][1]].append(e)

        lines.append("| 月份 | 工作日 | 重点项目 |")
        lines.append("|------|--------|---------|")
        for m in sorted(entries_by_month.keys(), reverse=True):
            me = entries_by_month[m]
            mp_days = defaultdict(int)
            for e in me:
                for p in e['projects']:
                    mp_days[p] += 1
            top_projs = "、".join(
                [f"{p}({c}天)" for p, c in
                 sorted(mp_days.items(), key=lambda x: -x[1])[:3]]
            )
            lines.append(f"| {m}月 | {len(me)}天 | {top_projs} |")
        lines.append("")

    # Key milestones
    if project_filter:
        lines.append(f"### 🏆 [{project_filter}] 关键节点\n")
    else:
        lines.append("### 🏆 关键里程碑\n")

    milestones = [(d, p, item) for d, p, item in all_items
                  if any(kw in item for kw in ["完成", "发布", "上线", "重构完成", "提测"])]

    if milestones:
        # Group by month
        mm = defaultdict(list)
        for d, p, item in milestones:
            mm[d[1]].append((d[2], p, item))

        for m in sorted(mm.keys(), reverse=True):
            items = mm[m]
            lines.append(f"**{m}月** ({len(items)} 项)")
            for d, p, item in items[:6]:
                lines.append(f"  - {d}日: [{p}] {item}")
            lines.append("")
    else:
        lines.append("（无显著里程碑节点）\n")

    # Work focus summary
    if project_filter:
        lines.append(f"### 💡 [{project_filter}] 工作重点\n")
    else:
        lines.append("### 💡 工作重点\n")

    for proj in sorted(project_days.keys(), key=lambda x: -project_days[x]):
        proj_items_list = [item for _, p, item in all_items if p == proj]
        # Extract top themes
        themes = set()
        for item in proj_items_list:
            # Extract common patterns
            if 'bug' in item.lower() or 'fix' in item.lower() or '修复' in item:
                themes.add('bug修复')
            if '发布' in item or '上线' in item or '提测' in item:
                themes.add('版本发布')
            if '开发' in item or '完成' in item or '实现' in item:
                themes.add('功能开发')
            if '重构' in item or '整理' in item or '优化' in item:
                themes.add('重构优化')
            if '模板' in item:
                themes.add('模板改版')
            if '特效' in item or '转场' in item or '滤镜' in item:
                themes.add('特效开发')

        theme_str = "、".join(themes) if themes else "日常开发维护"
        lines.append(f"**{proj}** ({project_items[proj]}项): {theme_str}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Summarize daily reports')
    parser.add_argument('--year', type=int, default=None, help='Year to summarize')
    parser.add_argument('--month', type=int, default=None, help='Month to summarize')
    parser.add_argument('--project', type=str, default=None, help='Project filter')
    parser.add_argument('--list', action='store_true', help='List available years')

    args = parser.parse_args()

    if args.list:
        years = list_available_years()
        print("可用的日报文件：")
        for y in years:
            filepath = os.path.join(REPORTS_DIR, f"{y}.md")
            size = os.path.getsize(filepath)
            entries = parse_report_file(filepath)
            print(f"  {y}年 — {len(entries)} 条日报 ({size/1024:.0f} KB)")
        return

    year = args.year
    if not year:
        years = list_available_years()
        year = years[0] if years else None

    if not year:
        print("错误：没有找到日报数据。")
        return

    result = summarize_year(year, args.month, args.project)
    print(result)


if __name__ == '__main__':
    main()
