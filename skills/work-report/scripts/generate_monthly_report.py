#!/usr/bin/env python3
"""Generate a monthly work report from reports/{year}.md.

The report is draft by default. --confirmed is retained for CLI compatibility but still requires user confirmation.
"""

import argparse
import datetime
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_parsing

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(SKILL_DIR, "reports")

MILESTONE_PATTERNS = {
    "版本": re.compile(r"版本|版本号|新版本|迭代|功能开发|需求|完成", re.I),
    "提测": re.compile(r"提测|测试|回归|联调", re.I),
    "发版": re.compile(r"发布|发版|上线|修复包|灰度", re.I),
    "验收": re.compile(r"验收|反馈|适配|验证|确认", re.I),
}


def parse_reports(path):
    """解析归档文件，返回 [{date, projects}]。

    日期识别、条目切分与「下个工作日」隔离统一走 report_parsing，不要再自己写正则。
    """
    entries = []
    for parsed in report_parsing.load_year_file(path):
        entries.append({
            "date": parsed["date"],
            "projects": {k: list(v) for k, v in parsed["projects"].items()},
        })
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def normalize(text):
    text = re.sub(r"\s+", " ", text).strip(" 。；;，,")
    return text


def chain_key(text):
    """Map daily items to a functional chain rather than a project label."""
    text = normalize(text)
    patterns = [
        (r"AI\s*Trim|AiTrim|时间轴|播放器|预览|结果页|片段", "AI Trim 功能链路"),
        (r"大屏|平板|适配", "大屏适配链路"),
        (r"特效|滤镜|转场|shader", "特效与滤镜链路"),
        (r"版本|提测|发布|上线|验收|回归|联调", "版本质量交付链路"),
    ]
    for pattern, name in patterns:
        if re.search(pattern, text, re.I):
            return name
    return "日常开发与问题修复"


def evidence(text):
    version_context = re.compile(
        r"(?:版本|版本号|新版本|迭代|提测|发版|发布|上线|修复包|灰度|构建|打包)"
        r"[^。；;，,\n]{0,24}?"
        r"(?<![\d.])(?:v|V)?\d+\.\d+(?:\.\d+){0,2}(?![\d.])"
        r"|(?<![\d.])(?:v|V)?\d+\.\d+(?:\.\d+){0,2}(?![\d.])"
        r"[^。；;，,\n]{0,24}?(?:版本|版本号|新版本|迭代|提测|发版|发布|上线|修复包|灰度|构建|打包)",
        re.I,
    )
    match = version_context.search(text)
    if not match:
        return None
    version = re.search(r"(?<![\d.])(?:v|V)?\d+\.\d+(?:\.\d+){0,2}(?![\d.])", match.group(0))
    return version.group(0) if version else None


def status_of(items):
    text = " ".join(item["text"] for item in items)
    if re.search(r"50%|部分|准备|计划|继续|推进|跟进|待确认", text):
        return "部分完成" if re.search(r"完成|修复|完成", text) else "进行中"
    if re.search(r"完成|修复|已接入|已适配|已发布|上线", text):
        return "完成"
    return "进行中"


def merge_tasks(items, limit=5):
    """Keep representative, outcome-oriented tasks instead of daily noise."""
    unique = []
    seen = set()
    for item in items:
        value = normalize(item)
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    if len(unique) <= limit:
        return unique
    # Prefer milestone-bearing items, then preserve source order.
    ranked = sorted(unique, key=lambda x: (not any(p.search(x) for p in MILESTONE_PATTERNS.values()), len(x)))
    selected = ranked[:limit - 1]
    remainder = len(unique) - len(selected)
    selected.append(f"其他相关开发、问题修复与验证（{remainder}项）")
    return selected


def classify(items):
    result = defaultdict(list)
    for item in items:
        matched = False
        for label, pattern in MILESTONE_PATTERNS.items():
            if pattern.search(item):
                result[label].append(item)
                matched = True
        if not matched:
            result["版本"].append(item)
    return result


def generate(year, month, confirmed=False):
    path = os.path.join(REPORTS_DIR, f"{year}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"日报文件不存在：{path}")
    # 不按 weekday 过滤：周末有实际工作记录的日期（如 2026-09-20 周日）也是工作日，
    # 按周一至周五过滤会少算天数。有日报记录即计为一天。
    parsed = [
        e for e in parse_reports(path)
        if e["date"].year == year and e["date"].month == month
    ]
    # A report can contain an editorial date heading plus the real daily block.
    # Count each calendar day once while retaining all project items.
    by_date = {}
    for entry in parsed:
        merged = by_date.setdefault(entry["date"], {"date": entry["date"], "projects": defaultdict(list)})
        for project, items in entry["projects"].items():
            merged["projects"][project].extend(items)
    entries = list(by_date.values())
    if not entries:
        raise ValueError(f"{year}年{month}月没有日报记录")

    chain_items = defaultdict(list)
    for entry in entries:
        active = [(project, item) for project, items in entry["projects"].items() for item in items]
        if not active:
            continue
        share = 1.0 / len(active)
        for project, item in active:
            chain_items[chain_key(item)].append({"text": normalize(item), "date": entry["date"], "project": project, "share": share})
    chains = sorted(chain_items, key=lambda c: (-sum(x["share"] for x in chain_items[c]), c))
    total_days = len(entries) or 1
    day_weights = {c: sum(x["share"] for x in chain_items[c]) for c in chains}
    weights = {c: round(day_weights[c] * 100 / total_days) for c in chains}
    if chains:
        weights[chains[-1]] += 100 - sum(weights.values())

    lines = ["月度工作汇报", "", f"汇报月份：{year}年{month}月", "姓名：饶辉", "岗位：Android开发", ""]
    lines += ["状态：草稿（--confirmed 仅兼容保留，仍需用户确认版本、提测、发版和验收结果）", "", f"本月工作天数：{len(entries)} 天", "归档记录天数不等于实际出勤；工作量按条目均分估算，需人工调整。", "", "一、本月主要工作"]
    pending = []
    for index, chain in enumerate(chains, 1):
        items = chain_items[chain]
        lines += [f"{index}. {chain}", "主要工作任务", chain, "任务成果情况"]
        for n, task in enumerate(merge_tasks([x["text"] for x in items]), 1):
            sources = [x for x in items if x["text"] == task]
            if not sources:
                sources = items
            version = evidence(task)
            source_dates = sorted({
                f"{source['date'].year}.{source['date'].month}.{source['date'].day}"
                for source in sources
            })
            date_text = ", ".join(source_dates)
            suffix = f"；版本/节点：{version}" if version else "；版本/节点：待确认"
            lines.append(f"（{n}）{task}（证据日期：{date_text}{suffix}）")
        lines += [f"工作量：{day_weights[chain]:.1f} 天，占比 {weights[chain]}%（估算）", f"状态：{status_of(items)}（关键词判断，待人工核验）"]
        pending.append(f"{chain}：补充版本号、提测/发版/验收最终结论")
        lines.append("")
    lines += ["二、本月亮点", "待人工从上述证据中选取，不自动推断成果价值。", "", "三、本月困难／卡点", "待人工确认实际困难及仍需跟进事项，不从任务关键词推断。", "", "待确认项（证据整理稿附注，最终表单不保留）", *[f"{i}. {item}" for i, item in enumerate(pending, 1)], ""]
    if confirmed:
        lines += ["确认输入", "未提供确认文件或确认内容；本次仍输出草稿，请用户明确确认后再归档。", ""]
    lines += ["填写检查", "1. 每个功能链路保留 2–5 项重点任务。", "2. 工作量按日期分配到功能链路，投入合计等于本月工作日，占比合计 100%。", "3. 版本、提测、发版、验收结果需由日报、Git 或用户确认支撑。"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate a monthly work report")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--confirmed", action="store_true", help="兼容旧 CLI；仍输出草稿并要求用户确认")
    args = parser.parse_args()
    if not 1 <= args.month <= 12:
        parser.error("--month 必须是 1-12")
    print(generate(args.year, args.month, args.confirmed))


if __name__ == "__main__":
    main()
