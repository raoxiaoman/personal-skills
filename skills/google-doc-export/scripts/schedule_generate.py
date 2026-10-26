from __future__ import annotations

import argparse
import re
from pathlib import Path

from schedule_models import SchedulePayload, ScheduleRow

SCHEDULE_CELL_ESTIMATE_RE = re.compile(r"^(\d+(?:\.\d+)?)天$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate schedule markdown/json artifacts from a requirement document.")
    parser.add_argument("--input-doc", required=True, help="Path to the local requirement markdown document.")
    parser.add_argument("--version", required=True, help="Version label, for example V1.650.")
    parser.add_argument("--feature", required=True, help="Feature name, for example AI Trim.")
    parser.add_argument("--output-md", required=True, help="Output path for the generated schedule markdown.")
    parser.add_argument("--output-json", required=True, help="Output path for the generated schedule json.")
    parser.add_argument("--sheet-name", default="", help="Optional explicit Google Sheets tab name.")
    parser.add_argument("--start-cell", default="A3", help="Start cell used by downstream sheet sync.")
    parser.add_argument("--dry-run", action="store_true", help="Print derived metadata without writing files.")
    return parser


def derive_sheet_name(version: str, feature: str, explicit_name: str, markdown_text: str) -> str:
    if explicit_name:
        return explicit_name

    for line in markdown_text.splitlines():
        title = line.strip()
        if not title.startswith("# "):
            continue
        prefix = f"# {version} "
        suffix = " 排期文档"
        if title.startswith(prefix) and title.endswith(suffix):
            display_name = title.removeprefix(prefix).removesuffix(suffix).strip()
            if display_name:
                return f"新版本{version} {display_name}"
            break

    return f"新版本{version} {feature}"


def normalize_date_for_internal(value: str) -> str:
    stripped = value.strip()
    if not stripped or stripped == "—":
        return stripped
    return stripped.replace(".", "/")


def format_date_for_display(value: str) -> str:
    stripped = value.strip()
    if not stripped or stripped == "—":
        return stripped
    return stripped.replace("/", ".")


def compose_schedule_cell(dev_estimate: str, expected_date: str) -> str:
    estimate = dev_estimate.strip()
    date_text = format_date_for_display(expected_date)
    if estimate and date_text and date_text != "—":
        return f"{estimate}/{date_text}"
    if estimate:
        return estimate
    return date_text


def split_schedule_cell(schedule_cell: str) -> tuple[str, str]:
    value = schedule_cell.strip()
    if not value or value == "—":
        return value if value == "—" else "", ""
    if "/" not in value:
        normalized_value = normalize_date_for_internal(value)
        if normalized_value != value and normalized_value:
            return "", normalized_value
        return value, ""

    left, right = value.rsplit("/", maxsplit=1)
    normalized_right = normalize_date_for_internal(right)
    if SCHEDULE_CELL_ESTIMATE_RE.fullmatch(left.strip()) and normalized_right:
        return left.strip(), normalized_right
    return value, ""


def render_markdown_stub(payload: SchedulePayload, source_doc: str) -> str:
    return "\n".join(
        [
            f"# {payload.version} 需求进度评估",
            "",
            f"> 来源文档：`{source_doc}`",
            "> 该文件由 google-doc-export skill 内置 schedule_generate.py 生成。",
            "",
            "## 一、总览",
            "",
            "| 版本 | 优先级 | 工作任务 | 产品负责人 | 开发负责人 | 开发排期 | 测试负责人 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            *[
                f"| {row.version_label} | {row.priority} | {row.task} | {row.product_owner} | {row.dev_owner} | {compose_schedule_cell(row.dev_estimate, row.remark.removeprefix('预计完成 '))} | {row.qa_owner} |"
                for row in payload.rows
            ],
            "",
            "## 二、详细拆解",
            "",
            "待补充。",
            "",
            "## 三、开发排期总览",
            "",
            "待补充。",
        ]
    )


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    normalized = line.replace(" ", "")
    return normalized.startswith("|---") or normalized.startswith("|-----")


def parse_schedule_row(cells: list[str]) -> ScheduleRow | None:
    if len(cells) == 7:
        dev_estimate, expected_date = split_schedule_cell(cells[5])
        remark = "" if not expected_date or expected_date == "—" else f"预计完成 {expected_date}"
        return ScheduleRow(
            version_label=cells[0],
            priority="" if cells[1] == "—" else cells[1],
            task=cells[2],
            product_owner=cells[3],
            product_progress="",
            dev_owner=cells[4],
            dev_estimate=dev_estimate,
            qa_owner=cells[6],
            qa_progress="",
            release_time="",
            remark=remark,
        )

    if len(cells) == 8:
        eta = normalize_date_for_internal(cells[7])
        remark = "" if eta in {"", "—"} else f"预计完成 {eta}"
        return ScheduleRow(
            version_label=cells[0],
            priority="" if cells[1] == "—" else cells[1],
            task=cells[2],
            product_owner=cells[3],
            product_progress="",
            dev_owner=cells[4],
            dev_estimate=cells[5],
            qa_owner=cells[6],
            qa_progress="",
            release_time="",
            remark=remark,
        )

    return None


def parse_overview_rows(text: str) -> list[ScheduleRow]:
    lines = text.splitlines()
    in_overview = False
    rows: list[ScheduleRow] = []

    for line in lines:
        if line.strip() == "## 一、总览":
            in_overview = True
            continue
        if in_overview and line.strip().startswith("## "):
            break
        if not in_overview:
            continue
        if not line.strip().startswith("|"):
            continue
        if "工作任务" in line and ("开发预估周期" in line or "开发排期" in line):
            continue
        if is_separator_row(line):
            continue

        cells = split_markdown_row(line)
        row = parse_schedule_row(cells)
        if row is None:
            continue
        rows.append(row)

    return rows


def build_payload_from_markdown(
    version: str,
    feature: str,
    sheet_name: str,
    start_cell: str,
    markdown_text: str,
) -> SchedulePayload:
    return SchedulePayload(
        version=version,
        feature=feature,
        sheet_name=sheet_name,
        start_cell=start_cell,
        rows=parse_overview_rows(markdown_text),
    )


def main() -> int:
    args = build_parser().parse_args()
    input_doc = Path(args.input_doc)
    output_md = Path(args.output_md)
    output_json = Path(args.output_json)
    markdown_text = input_doc.read_text(encoding="utf-8")
    sheet_name = derive_sheet_name(args.version, args.feature, args.sheet_name, markdown_text)

    payload = build_payload_from_markdown(
        version=args.version,
        feature=args.feature,
        sheet_name=sheet_name,
        start_cell=args.start_cell,
        markdown_text=markdown_text,
    )

    if args.dry_run:
        print(f"input_doc={input_doc}")
        print(f"output_md={output_md}")
        print(f"output_json={output_json}")
        print(f"sheet_name={sheet_name}")
        print(f"start_cell={args.start_cell}")
        print(f"rows={len(payload.rows)}")
        if payload.rows:
            print(f"first_task={payload.rows[0].task}")
        return 0

    output_md.write_text(render_markdown_stub(payload, str(input_doc)), encoding="utf-8")
    payload.write_json_file(output_json)
    print(f"Wrote markdown: {output_md}")
    print(f"Wrote json: {output_json}")
    print(f"rows={len(payload.rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
