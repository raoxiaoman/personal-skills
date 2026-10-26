#!/usr/bin/env python3
"""
绩效考核表生成器（2026 新模板）
根据日报记录、git 提交记录，基于 2026 新模板生成绩效考核表 xlsx。
"""

import argparse
import re
import subprocess
import sys as _sys
from copy import copy
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

_sys.path.insert(0, str(Path(__file__).parent))
import report_parsing

REPORTS_DIR = Path.home() / ".claude" / "skills" / "work-report" / "reports"
REPOS = {
    "YouCut": Path.home() / "code" / "work" / "YouCut" / "YouCutAndroid",
    "VideoGuru": Path.home() / "code" / "work" / "videoGuru" / "VideoGuruAndroid",
}
USER_NAME = "饶辉"
GIT_AUTHOR = "raohui"
TEMPLATE_INFO = {"入职时间": "2022.05.05", "岗位": "Android开发", "主管": "包思亮"}
TEMPLATE_PATH = Path.home() / "Documents" / "绩效" / "附件1 ：员工绩效考核评价表（2026）.xlsx"


def parse_args():
    parser = argparse.ArgumentParser(description="生成绩效考核表（2026 新模板）")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="年份")
    parser.add_argument("--half", choices=["first", "second"], required=True, help="上半年/下半年")
    parser.add_argument("--name", default=USER_NAME, help="被考核人姓名")
    parser.add_argument("--output", required=True, help="输出 xlsx 路径")
    parser.add_argument("--scores", help="自评分数，逗号分隔，如 92,90,90,95", default=None)
    return parser.parse_args()


def get_date_range(year, half):
    if half == "first":
        return f"{year}-01-01", f"{year}-06-30"
    return f"{year}-07-01", f"{year}-12-31"


def parse_daily_reports(year):
    """读取归档日报。日期格式与条目切分统一走 report_parsing，不要再自己写正则。"""
    report_file = REPORTS_DIR / f"{year}.md"
    if not report_file.exists():
        return []
    entries = []
    for parsed in report_parsing.load_year_file(report_file, year):
        items = [
            {"project": proj, "text": text}
            for proj, texts in parsed["projects"].items()
            for text in texts
        ]
        entries.append({"date": parsed["date"].strftime("%Y-%m-%d"), "items": items})
    return entries


def collect_git_commits(start_date, end_date):
    all_commits = []
    for proj_name, repo_path in REPOS.items():
        if not repo_path.exists():
            continue
        result = subprocess.run(
            [
                "git", "log",
                f"--author={GIT_AUTHOR}",
                f"--since={start_date}",
                f"--until={end_date}",
                "--oneline", "--format=%H|%s|%ai",
            ],
            cwd=str(repo_path), capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                all_commits.append({
                    "project": proj_name,
                    "hash": parts[0],
                    "subject": parts[1],
                    "date": parts[2][:10],
                })
    return all_commits


def _dedupe(items):
    seen, result = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _polish_youcut(items):
    if not items:
        return ""
    lines = []
    lines.append("负责 YouCut 上半年重点需求开发与版本交付，重点完成模板改版链路优化、特效资源接入、会员展示控制与代码优化等工作，主要完成以下内容：")
    lines.append("")
    lines.append("1.版本 V1.711.1217 模板改版相关开发：围绕外露模板改版持续处理 Discover 页面、动态封面滚动切换逻辑及播放页面优化等工作，推动模板链路体验完善")
    lines.append("2.版本 V1.711.1217 特效资源制作与接入：完成 VFX-Fire_Sparks、VFX-Fire_Blaze、VFX-Glass_Burst、VFX-Glass_Break、VFX-Petal_Fall、VFX-Dust Spread 等多组特效制作、配置与效果落地，支撑版本内容供给")
    lines.append("3.会员与配置能力支持：完成云端控制 free trial 显示（可按国家控制）等配置能力支持，配合需求落地与版本验证")
    lines.append("4.代码优化与版本收口：完成 DEBUG 模式管理，并持续处理模板改版相关提测问题与验收反馈，推动版本按节奏收口")
    return "\n".join(lines)


def _polish_vg(items):
    if not items:
        return ""
    lines = []
    lines.append("负责 Maker / VideoGuru 上半年重点版本与核心需求开发，重点完成 AI Trim 功能建设、视频稳像能力完善、AI 任务管理机制引入，以及 1.610.191 / 1.611.193 / 1.612.194 版本问题收口，主要完成以下内容：")
    lines.append("")
    lines.append("1.版本 V1.620 AI Trim 功能开发：负责 AI Trim 展开页、服务端接口联调与处理逻辑 Module 封装、操作页交互、Done 应用结果、FAQ 页面与特殊拦截、自测等需求开发，覆盖入口判断、会员/广告解锁逻辑、按词选取删除、素材跟随提醒、无网/无音轨/纯图片等核心场景")
    lines.append("2.AI Trim 结果链路与状态联动优化：持续完善 AI Trim 结果页联动、referenceId 对齐、预览效果剥离、状态同步、进度恢复、进度条 UI 及任务浮窗显示等细节，推进功能链路联调与体验收口")
    lines.append("3.视频稳像功能建设与版本收口：围绕视频稳像能力持续处理提测反馈，覆盖稳像与 enhance/cutout 联动问题、TaskManager 相关逻辑完善、稳像埋点补充及版本问题收口，并跟进 1.610.191 / 1.611.193 / 1.612.194 等版本修复包发布与质量观察")
    lines.append("4.AI 任务相关处理链路优化：结合 Enhance / Cutout 等场景持续完善 AI 任务相关管理逻辑，并处理无网等异常场景下的链路表现问题")
    lines.append("5.版本资源与附加需求支持：负责制作上线足球封面、新增 1 组特效等补充需求，支撑版本内容完善与交付收口")
    return "\n".join(lines)


def _polish_quality(items_yc, items_vg):
    lines = []
    lines.append("参与 2026 上半年多个版本的质量保障与交付收口，围绕提测问题闭环、线上稳定性控制与核心体验优化持续推进，主要完成以下工作：")
    lines.append("")
    lines.append("1.提测问题闭环与版本交付保障：及时处理各轮提测反馈问题，持续收口模板改版、AI Trim、稳像、多任务处理等核心链路问题，保障本人负责需求按节奏交付")
    lines.append("2.线上质量响应与稳定性保障：持续处理异常反馈与版本问题，快速定位并修复重点问题，降低版本风险，保障上半年版本稳定性")
    lines.append("3.体验与性能优化：持续关注播放预览、处理进度、交互响应、内存与启动体验等关键指标，推动产品整体体验与稳定性持续改善")
    return "\n".join(lines)


def _polish_refactor(youcut_items, vg_items):
    all_text = " ".join(youcut_items + vg_items)
    lines = []
    lines.append("在版本迭代之外，持续推进技术债务治理与工程架构优化，主要涉及：")
    lines.append("")
    themes = []
    idx = 1
    if "重构" in all_text or "基类" in all_text or "插件化" in all_text:
        themes.append(f"{idx}.代码架构深度重构与模块化治理：推动编辑页控件控制基类重构，以配置模式替代传统方法复写，建立单向数据流开发范式；回退栈操作类型判定与文案输出统一封装至独立工作类，有效提升模块复用性与后续功能扩展效率")
        idx += 1
    if "埋点" in all_text or "事件" in all_text:
        themes.append(f"{idx}.数据采集体系与精细化运营支撑：新增 user_type 用户身份区分等多维度埋点，完善用户行为数据采集与分析链路，为精细化运营策略提供底层数据能力支撑")
        idx += 1
    if "编译" in all_text or "BuildShader" in all_text:
        themes.append(f"{idx}.编译工具链持续优化与提效：围绕特效编译工具与编译库持续开展整理、优化与配置调整，提升编译效率和后续维护便利性")
        idx += 1
    if "依赖" in all_text:
        themes.append(f"{idx}.依赖治理与技术栈升级：推进 Captions、yuv 等关键依赖版本更新，移除冗余依赖项，精简项目结构，降低构建复杂度与潜在依赖冲突风险")
        idx += 1
    if "UI" in all_text or "适配" in all_text:
        themes.append(f"{idx}.系统兼容性与交互体验优化：持续处理系统栏适配、键盘交互及页面异常问题，提升系统兼容稳定性和用户交互体验")
        idx += 1
    lines.extend(themes)
    lines.append("")
    lines.append("以上架构治理与优化工作有效降低了技术债务，提升了整体工程质量和研发效率。")
    return "\n".join(lines) if themes else ""


def classify_and_summarize(entries, commits):
    youcut_items, vg_items = [], []
    for entry in entries:
        for item in entry["items"]:
            proj, text = item["project"], item["text"]
            if "YouCut" in proj or "youcut" in proj.lower() or "Yocut" in proj:
                youcut_items.append(text)
            elif "VideoGuru" in proj or "Guru" in proj or "Maker" in proj or "maker" in proj:
                vg_items.append(text)
    youcut_items = _dedupe(youcut_items)
    vg_items = _dedupe(vg_items)
    items = [
        {"name": "VideoGuru/Maker 版本功能开发与工具类重构", "weight": 0.25, "description": _polish_vg(vg_items) or "完成 VideoGuru/Maker 版本功能开发与代码维护工作"},
        {"name": "YouCut 版本功能开发与模板改版", "weight": 0.35, "description": _polish_youcut(youcut_items) or "完成 YouCut 版本功能开发、模板改版与 Bug 修复工作"},
        {"name": "功能改造与模块优化", "weight": 0.20, "description": _polish_refactor(youcut_items, vg_items)},
        {"name": "开发质量与应用性能", "weight": 0.20, "description": _polish_quality(youcut_items, vg_items)},
    ]
    return [item for item in items if item["description"]]


def _rich_desc(desc_text):
    if not desc_text:
        return desc_text
    parts = desc_text.split("\n\n", 1)
    blocks = [TextBlock(InlineFont(sz=10), parts[0] + "\n\n")]
    if len(parts) > 1 and parts[1]:
        for i, line in enumerate(parts[1].split("\n")):
            if not line.strip():
                continue
            if i > 0:
                blocks.append(TextBlock(InlineFont(sz=10), "\n"))
            c = line.find("：")
            if 0 < c < 45:
                blocks.append(TextBlock(InlineFont(b=True, sz=10), line[:c]))
                blocks.append(TextBlock(InlineFont(sz=10), line[c:]))
            else:
                blocks.append(TextBlock(InlineFont(sz=10), line))
    return CellRichText(blocks) if len(blocks) > 1 else desc_text


def create_xlsx(items, name, year, half, output_path, scores=None):
    src_wb = load_workbook(TEMPLATE_PATH)
    src_ws = src_wb[src_wb.sheetnames[0]]

    wb = load_workbook(TEMPLATE_PATH)
    ws = wb[wb.sheetnames[0]]

    ws["C3"] = name
    ws["E3"] = TEMPLATE_INFO["入职时间"]
    ws["G3"] = TEMPLATE_INFO["岗位"]
    ws["J3"] = TEMPLATE_INFO["主管"]

    num_items = len(items)
    score_list = [90] * num_items
    if scores:
        raw = [s.strip() for s in scores.split(",") if s.strip()]
        try:
            parsed = [int(s) for s in raw]
        except ValueError:
            raise SystemExit(
                f"错误: --scores 只能是逗号分隔的整数，收到：{scores!r}\n"
                f"示例：--scores 92,91,90,88"
            )
        if len(parsed) > num_items:
            print(f"提示: --scores 给了 {len(parsed)} 个分数，只有前 {num_items} 个生效（共 {num_items} 项任务）")
        score_list[:len(parsed)] = parsed[:num_items]

    data_start = 8
    total_row = data_start + num_items
    grade_row = total_row + 1

    def copy_row_style(src_row, dst_row):
        for col in range(1, 12):
            src = src_ws.cell(row=src_row, column=col)
            dst = ws.cell(row=dst_row, column=col)
            dst._style = copy(src._style)
            dst.font = copy(src.font)
            dst.fill = copy(src.fill)
            dst.border = copy(src.border)
            dst.alignment = copy(src.alignment)
            dst.number_format = src.number_format
        ws.row_dimensions[dst_row].height = src_ws.row_dimensions[src_row].height

    extra_rows = max(0, total_row - 11)

    # 清掉旧的工作自评区到绩效等级行之间的内容与合并
    merges_to_remove = []
    tail_merges = []
    for rng in ws.merged_cells.ranges:
        if rng.min_row >= 8 and rng.max_row <= 12:
            merges_to_remove.append(str(rng))
        elif rng.min_row >= 14:
            tail_merges.append((rng.min_row, rng.min_col, rng.max_row, rng.max_col))
            merges_to_remove.append(str(rng))
    for rng in merges_to_remove:
        ws.unmerge_cells(rng)

    if extra_rows:
        ws.insert_rows(11, extra_rows)

        for src_row in range(14, src_ws.max_row + 1):
            dst_row = src_row + extra_rows
            for col in range(1, 12):
                src = src_ws.cell(row=src_row, column=col)
                dst = ws.cell(row=dst_row, column=col)
                dst._style = copy(src._style)
                dst.font = copy(src.font)
                dst.fill = copy(src.fill)
                dst.border = copy(src.border)
                dst.alignment = copy(src.alignment)
                dst.number_format = src.number_format
            ws.row_dimensions[dst_row].height = src_ws.row_dimensions[src_row].height

    for min_row, min_col, max_row, max_col in tail_merges:
        ws.merge_cells(
            start_row=min_row + extra_rows,
            start_column=min_col,
            end_row=max_row + extra_rows,
            end_column=max_col,
        )

    # 重建数据行
    for row in range(data_start, total_row):
        copy_row_style(10, row)
        for col in range(2, 12):
            ws.cell(row=row, column=col).value = None

    for i, item in enumerate(items):
        row = data_start + i
        ws.cell(row=row, column=2).value = i + 1
        ws.cell(row=row, column=3).value = item["name"]
        ws.cell(row=row, column=4).value = item["weight"]
        ws.cell(row=row, column=5).value = _rich_desc(item["description"])
        ws.cell(row=row, column=6).value = score_list[i]
        ws.cell(row=row, column=7).value = f"=F{row}*D{row}"
        ws.cell(row=row, column=8).value = 90
        ws.cell(row=row, column=9).value = 90
        ws.cell(row=row, column=10).value = f"=(H{row}*D{row}+I{row}*D{row})/2"
        ws.cell(row=row, column=11).value = ""
        ws.row_dimensions[row].height = max(42, min(240, len(item["description"]) * 0.9))

    # 重建总分与等级行
    copy_row_style(11, total_row)
    copy_row_style(12, grade_row)

    for col in range(2, 12):
        ws.cell(row=total_row, column=col).value = None
        ws.cell(row=grade_row, column=col).value = None

    ws.merge_cells(f"B{total_row}:E{total_row}")
    ws.merge_cells(f"H{total_row}:I{total_row}")
    ws.merge_cells(f"B{grade_row}:E{grade_row}")
    ws.merge_cells(f"H{grade_row}:I{grade_row}")

    ws[f"B{total_row}"] = "员工自评总分"
    ws[f"G{total_row}"] = f"=SUM(G{data_start}:G{total_row-1})"
    ws[f"H{total_row}"] = "主管评分总分"
    ws[f"J{total_row}"] = f"=SUM(J{data_start}:J{total_row-1})"

    ws[f"B{grade_row}"] = "员工绩效等级"
    ws[f"G{grade_row}"] = f'=IF(G{total_row}="","",IF(G{total_row}>=96,"A",IF(G{total_row}>=90,"B+",IF(G{total_row}>=80,"B",IF(G{total_row}>=70,"B-","C")))))'
    ws[f"H{grade_row}"] = "主管绩效等级"
    ws[f"J{grade_row}"] = f'=IF(J{total_row}="","",IF(J{total_row}>=96,"A",IF(J{total_row}>=90,"B+",IF(J{total_row}>=80,"B",IF(J{total_row}>=70,"B-","C")))))'

    wb.save(output_path)
    print(f"✅ 已生成: {output_path}")
    print(f"   共 {num_items} 项工作任务")
    print(f"   Sheet: {ws.title}")


def print_summary(items, entries, commits, year, half):
    half_label = "上半年" if half == "first" else "下半年"
    print(f"\n{'='*60}")
    print(f"  {year}年{half_label} 绩效考核表 - 摘要")
    print(f"  被考核人: {USER_NAME}")
    print(f"  日报条目: {sum(len(e['items']) for e in entries)} 条")
    print(f"  Git 提交: {len(commits)} 个")
    print(f"{'='*60}\n")
    for i, item in enumerate(items):
        print(f"  {i+1}. [{item['weight']*100:.0f}%] {item['name']}")
        desc_preview = item['description'][:60].replace("\n", " ") + ("..." if len(item['description']) > 60 else "")
        print(f"     {desc_preview}")
    print()


def main():
    args = parse_args()
    start_date, end_date = get_date_range(args.year, args.half)
    print(f"📋 正在收集 {args.year}年{'上半年' if args.half == 'first' else '下半年'} 工作数据...")
    entries = parse_daily_reports(args.year)
    period_entries = [e for e in entries if start_date <= e['date'] <= end_date]
    print(f"   日报条目: {sum(len(e['items']) for e in period_entries)} 条 (在考核期内)")
    commits = collect_git_commits(start_date, end_date)
    print(f"   Git 提交: {len(commits)} 个")
    items = classify_and_summarize(period_entries, commits)
    print_summary(items, period_entries, commits, args.year, args.half)
    create_xlsx(items, args.name, args.year, args.half, args.output, scores=args.scores)
    print("\n💡 提示：请在 Excel 中补充以下内容后保存：")
    print("   1. 如需调整，可修改结果自评、工作达成效率、工作态度及责任心分数")
    print("   2. 如需主管评分，可填写主管评价栏")


if __name__ == '__main__':
    main()
