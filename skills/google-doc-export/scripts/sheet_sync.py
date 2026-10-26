from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from schedule_models import SchedulePayload, ScheduleRow, rows_to_tsv

CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


@dataclass(slots=True)
class SyncPlan:
    sheet_url: str
    sheet_name: str
    start_cell: str
    target_range: str
    replace: bool
    format_level: str
    row_count: int
    tsv: str
    preserve_footer_notes: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync generated schedule json to Google Sheets.")
    parser.add_argument("--sheet-url", required=True, help="Target Google Sheets url.")
    parser.add_argument("--sheet-name", default="", help="Optional explicit sheet tab name.")
    parser.add_argument("--start-cell", default="", help="Optional explicit start cell, overrides json.")
    parser.add_argument("--input-json", required=True, help="Path to schedule json payload.")
    parser.add_argument("--replace", action="store_true", help="Replace the existing target range with payload rows.")
    parser.add_argument("--format", choices=["none", "center", "full"], default="center", help="Requested formatting level.")
    parser.add_argument("--dry-run", action="store_true", help="Print target range and TSV without performing sync.")
    parser.add_argument("--output-tsv", default="", help="Optional path to write the generated TSV payload.")
    parser.add_argument("--output-plan", default="", help="Optional path to write the sync plan json.")
    parser.add_argument(
        "--execution-mode",
        choices=["dry-run", "handoff"],
        default="handoff",
        help="Execution mode. 'handoff' prints the exact next-step instructions for browser-based sync.",
    )
    return parser


def compute_target_range(start_cell: str, row_count: int, column_end: str = "K") -> str:
    match = CELL_RE.fullmatch(start_cell)
    if not match:
        raise ValueError(f"Unsupported start cell: {start_cell}")
    _, start_row = match.groups()
    start_row_num = int(start_row)
    end_row_num = start_row_num + max(row_count - 1, 0)
    return f"{start_cell}:{column_end}{end_row_num}"


def format_schedule_cell(dev_estimate: str, remark: str) -> str:
    estimate = dev_estimate.strip()
    expected_date = remark.removeprefix("预计完成 ").strip()
    if estimate and expected_date:
        return f"{estimate}/{expected_date.replace('/', '.')}"
    if estimate:
        return estimate
    if expected_date:
        return expected_date.replace('/', '.')
    return ""


def transform_rows_for_sheet(payload: SchedulePayload) -> SchedulePayload:
    transformed_rows = [
        ScheduleRow(
            version_label=row.version_label,
            priority=row.priority,
            task=row.task,
            product_owner=row.product_owner,
            product_progress=row.product_progress,
            dev_owner=row.dev_owner,
            dev_estimate=format_schedule_cell(row.dev_estimate, row.remark),
            qa_owner=row.qa_owner,
            qa_progress=row.qa_progress,
            release_time=row.release_time,
            remark="",
        )
        for row in payload.rows
    ]
    return SchedulePayload(
        version=payload.version,
        feature=payload.feature,
        sheet_name=payload.sheet_name,
        start_cell=payload.start_cell,
        rows=transformed_rows,
    )


def build_sync_plan(
    payload: SchedulePayload,
    sheet_url: str,
    sheet_name: str,
    start_cell: str,
    replace: bool,
    format_level: str,
) -> SyncPlan:
    return SyncPlan(
        sheet_url=sheet_url,
        sheet_name=sheet_name,
        start_cell=start_cell,
        target_range=compute_target_range(start_cell, len(payload.rows)),
        replace=replace,
        format_level=format_level,
        row_count=len(payload.rows),
        tsv=rows_to_tsv(payload.rows),
    )


def write_optional_output(file_path: str, content: str) -> None:
    if not file_path:
        return
    Path(file_path).write_text(content, encoding="utf-8")


def render_handoff(sync_plan: SyncPlan) -> str:
    return "\n".join(
        [
            "Execution handoff:",
            f"1. Open sheet: {sync_plan.sheet_url}",
            f"2. Switch to tab: {sync_plan.sheet_name}",
            f"3. Select target range: {sync_plan.target_range}",
            "4. Paste the TSV payload as a block overwrite.",
            f"5. Apply formatting level: {sync_plan.format_level}",
            "6. If formatting level is 'center', set horizontal center, vertical middle, and wrapping as needed.",
            f"7. Row count to verify after paste: {sync_plan.row_count}",
        ]
    )


def main() -> int:
    args = build_parser().parse_args()
    payload = SchedulePayload.from_json_file(args.input_json)
    payload = transform_rows_for_sheet(payload)
    sheet_name = args.sheet_name or payload.sheet_name
    start_cell = args.start_cell or payload.start_cell
    sync_plan = build_sync_plan(
        payload=payload,
        sheet_url=args.sheet_url,
        sheet_name=sheet_name,
        start_cell=start_cell,
        replace=args.replace,
        format_level=args.format,
    )

    print(f"sheet_url={sync_plan.sheet_url}")
    print(f"sheet_name={sync_plan.sheet_name}")
    print(f"start_cell={sync_plan.start_cell}")
    print(f"target_range={sync_plan.target_range}")
    print(f"replace={sync_plan.replace}")
    print(f"format={sync_plan.format_level}")
    print(f"rows={sync_plan.row_count}")
    print(f"execution_mode={args.execution_mode}")

    if args.output_tsv:
        write_optional_output(args.output_tsv, sync_plan.tsv)
        print(f"Wrote TSV payload: {args.output_tsv}")

    if args.output_plan:
        write_optional_output(args.output_plan, sync_plan.to_json())
        print(f"Wrote sync plan: {args.output_plan}")

    if args.dry_run or not payload.rows:
        if payload.rows:
            print("--- TSV START ---")
            print(sync_plan.tsv)
            print("--- TSV END ---")
        else:
            print("No rows found in payload. Nothing to sync.")
        return 0

    print(render_handoff(sync_plan))
    print("Real in-browser execution should be performed by a higher-level Skill or Playwright MCP session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())