from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DATE_HEADER_RE = re.compile(r"^> 开始日期：(\d{4}-\d{2}-\d{2})")
SKIP_DATES_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
NUMERIC_ESTIMATE_RE = re.compile(r"^(\d+(?:\.\d+)?)天$")
SECTION_HEADING_RE = re.compile(r"^## ")
COMMENT_SECTION_THREE = "[//]: # (## 三、开发排期总览)"


@dataclass(slots=True)
class OverviewRow:
    version_label: str
    priority: str
    task: str
    product_owner: str
    dev_owner: str
    dev_estimate: str
    qa_owner: str
    expected_date: str

    def schedule_cell(self) -> str:
        return compose_schedule_cell(self.dev_estimate, self.expected_date)

    def to_cells(self) -> list[str]:
        return [
            self.version_label,
            self.priority,
            self.task,
            self.product_owner,
            self.dev_owner,
            self.schedule_cell(),
            self.qa_owner,
        ]


@dataclass(slots=True)
class DailyPlanRow:
    day_label: str
    weekday_label: str
    work_summary: str


@dataclass(slots=True)
class ScheduleDocument:
    lines: list[str]
    start_date: date
    skip_dates: set[date]
    overview_rows: list[OverviewRow]
    section_one_range: tuple[int, int]
    section_three_range: tuple[int, int]


class ScheduleParseError(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh linked schedule sections from overview table.")
    parser.add_argument("--input", required=True, help="Path to docs/<version>/schedule.md")
    parser.add_argument("--output", default="", help="Optional output path. Defaults to in-place overwrite when --write is used.")
    parser.add_argument("--write", action="store_true", help="Overwrite the target markdown file.")
    parser.add_argument(
        "--recalculate-overview-dates",
        action="store_true",
        help="Recalculate overview expected dates from start date, skipped dates, dev owner, and numeric estimates.",
    )
    parser.add_argument(
        "--schedule-owner",
        default="",
        help="Optional dev owner used for section three generation. Defaults to the owner with the most numeric-estimate rows.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the refreshed markdown instead of writing files.")
    return parser


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    normalized = line.replace(" ", "")
    return normalized.startswith("|---") or normalized.startswith("|-----")


def parse_start_date(lines: list[str]) -> date:
    for line in lines:
        match = DATE_HEADER_RE.match(line.strip())
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    raise ScheduleParseError("Missing start date line like '> 开始日期：2026-05-27（周三）'.")


def parse_skip_dates(lines: list[str], year: int) -> set[date]:
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("> 跳过周末："):
            continue
        return {
            date(year, int(month), int(day))
            for month, day in SKIP_DATES_RE.findall(stripped)
        }
    return set()


def find_section_range(lines: list[str], heading: str, allow_comment_heading: bool = False) -> tuple[int, int]:
    start_index = -1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == heading or (allow_comment_heading and stripped == COMMENT_SECTION_THREE):
            start_index = index
            break
    if start_index == -1:
        raise ScheduleParseError(f"Missing section heading: {heading}")

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if SECTION_HEADING_RE.match(lines[index].strip()):
            end_index = index
            break
    return start_index, end_index


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
    if NUMERIC_ESTIMATE_RE.fullmatch(left.strip()) and normalized_right:
        return left.strip(), normalized_right
    return value, ""


def parse_overview_row_cells(cells: list[str]) -> OverviewRow | None:
    if len(cells) == 7:
        dev_estimate, expected_date = split_schedule_cell(cells[5])
        return OverviewRow(
            version_label=cells[0],
            priority=cells[1],
            task=cells[2],
            product_owner=cells[3],
            dev_owner=cells[4],
            dev_estimate=dev_estimate,
            qa_owner=cells[6],
            expected_date=expected_date,
        )

    if len(cells) == 8:
        return OverviewRow(
            version_label=cells[0],
            priority=cells[1],
            task=cells[2],
            product_owner=cells[3],
            dev_owner=cells[4],
            dev_estimate=cells[5],
            qa_owner=cells[6],
            expected_date=normalize_date_for_internal(cells[7]),
        )

    return None


def parse_overview_rows(lines: list[str], section_range: tuple[int, int]) -> list[OverviewRow]:
    rows: list[OverviewRow] = []
    start_index, end_index = section_range
    for line in lines[start_index:end_index]:
        if not line.strip().startswith("|"):
            continue
        if "工作任务" in line and ("开发预估周期" in line or "开发排期" in line):
            continue
        if is_separator_row(line):
            continue
        cells = split_markdown_row(line)
        row = parse_overview_row_cells(cells)
        if row is None:
            continue
        rows.append(row)
    if not rows:
        raise ScheduleParseError("No overview rows found in section one.")
    return rows


def parse_schedule_document(markdown_text: str) -> ScheduleDocument:
    lines = markdown_text.splitlines()
    start_date = parse_start_date(lines)
    skip_dates = parse_skip_dates(lines, start_date.year)
    section_one_range = find_section_range(lines, "## 一、总览")
    section_three_range = find_section_range(lines, "## 三、开发排期总览", allow_comment_heading=True)
    overview_rows = parse_overview_rows(lines, section_one_range)
    return ScheduleDocument(
        lines=lines,
        start_date=start_date,
        skip_dates=skip_dates,
        overview_rows=overview_rows,
        section_one_range=section_one_range,
        section_three_range=section_three_range,
    )


def parse_numeric_estimate(value: str) -> float | None:
    match = NUMERIC_ESTIMATE_RE.fullmatch(value.strip())
    if not match:
        return None
    return float(match.group(1))


def is_workday(current: date, skip_dates: set[date]) -> bool:
    return current.weekday() < 5 and current not in skip_dates


def next_workday(current: date, skip_dates: set[date]) -> date:
    probe = current + timedelta(days=1)
    while not is_workday(probe, skip_dates):
        probe += timedelta(days=1)
    return probe


def allocate_completion_dates(rows: list[OverviewRow], start_date: date, skip_dates: set[date]) -> list[OverviewRow]:
    owner_state: dict[str, tuple[date, float]] = {}
    refreshed_rows: list[OverviewRow] = []

    for row in rows:
        estimate_days = parse_numeric_estimate(row.dev_estimate)
        if estimate_days is None or not row.dev_owner:
            refreshed_rows.append(row)
            continue

        owner = row.dev_owner
        current_day, remaining_capacity = owner_state.get(owner, (start_date, 1.0))
        while not is_workday(current_day, skip_dates):
            current_day = next_workday(current_day, skip_dates)
            remaining_capacity = 1.0

        remaining_work = estimate_days
        completion_day = current_day

        while remaining_work > 0:
            if remaining_capacity <= 0:
                current_day = next_workday(current_day, skip_dates)
                remaining_capacity = 1.0

            consumed = min(remaining_capacity, remaining_work)
            remaining_capacity -= consumed
            remaining_work -= consumed
            completion_day = current_day

            if remaining_work > 0 and remaining_capacity <= 0:
                current_day = next_workday(current_day, skip_dates)
                remaining_capacity = 1.0

        owner_state[owner] = (current_day, remaining_capacity)
        refreshed_rows.append(
            OverviewRow(
                version_label=row.version_label,
                priority=row.priority,
                task=row.task,
                product_owner=row.product_owner,
                dev_owner=row.dev_owner,
                dev_estimate=row.dev_estimate,
                qa_owner=row.qa_owner,
                expected_date=format_month_day(completion_day),
            )
        )

    return refreshed_rows


def format_month_day(value: date) -> str:
    return f"{value.month}/{value.day}"


def weekday_label(value: date) -> str:
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return labels[value.weekday()]


def choose_schedule_owner(rows: list[OverviewRow], explicit_owner: str) -> str:
    if explicit_owner:
        return explicit_owner

    scores: dict[str, int] = {}
    for row in rows:
        if parse_numeric_estimate(row.dev_estimate) is None:
            continue
        if not row.dev_owner:
            continue
        scores[row.dev_owner] = scores.get(row.dev_owner, 0) + 1

    if not scores:
        return ""
    return max(scores.items(), key=lambda item: item[1])[0]


def shorten_task_name(task: str) -> str:
    parts = [part.strip() for part in task.split("—", maxsplit=1)]
    return parts[1] if len(parts) == 2 else task.strip()


def build_daily_plan_rows(rows: list[OverviewRow], schedule_owner: str, skip_dates: set[date], year: int) -> list[DailyPlanRow]:
    grouped: dict[date, list[str]] = {}
    deferred_tasks: list[str] = []

    for row in rows:
        if schedule_owner and row.dev_owner != schedule_owner:
            if "提测期间" in row.dev_estimate:
                deferred_tasks.append(shorten_task_name(row.task))
            continue

        estimate_days = parse_numeric_estimate(row.dev_estimate)
        if estimate_days is None:
            if "提测期间" in row.dev_estimate:
                deferred_tasks.append(shorten_task_name(row.task))
            continue
        if not row.expected_date or row.expected_date == "—":
            continue

        month, day = row.expected_date.split("/")
        current_date = date(year, int(month), int(day))
        while not is_workday(current_date, skip_dates):
            current_date = next_workday(current_date, skip_dates)

        grouped.setdefault(current_date, []).append(shorten_task_name(row.task))

    plan_rows = [
        DailyPlanRow(
            day_label=format_month_day(plan_date),
            weekday_label=weekday_label(plan_date),
            work_summary=" + ".join(tasks),
        )
        for plan_date, tasks in sorted(grouped.items())
    ]

    if deferred_tasks:
        plan_rows.append(
            DailyPlanRow(
                day_label="提测期间",
                weekday_label="—",
                work_summary=" + ".join(deferred_tasks),
            )
        )

    return plan_rows


def render_aligned_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(cells: list[str]) -> str:
        parts = [f" {cell.ljust(widths[index])} " for index, cell in enumerate(cells)]
        return f"|{'|'.join(parts)}|"

    separator = "|" + "|".join("-" * (width + 2) for width in widths) + "|"
    return [format_row(headers), separator, *[format_row(row) for row in rows]]


def render_overview_section(rows: list[OverviewRow]) -> list[str]:
    headers = ["版本", "优先级", "工作任务", "产品负责人", "开发负责人", "开发排期", "测试负责人"]
    body = [row.to_cells() for row in rows]
    return ["## 一、总览", "", *render_aligned_table(headers, body), ""]


def render_section_three(rows: list[DailyPlanRow], skip_dates: set[date]) -> list[str]:
    headers = ["日期", "星期", "工作内容"]
    body = [[row.day_label, row.weekday_label, row.work_summary] for row in rows]
    section_lines = ["## 三、开发排期总览", "", *render_aligned_table(headers, body), ""]

    if skip_dates:
        notes = "、".join(f"{value.month}/{value.day}（{weekday_label(value)}）" for value in sorted(skip_dates))
        section_lines.extend([
            f"> 注：{notes} 为休息日，不计入排期。",
            "",
        ])

    section_lines.extend([
        "> 注：本节默认由总览表刷新生成；如需调整联动结果，请优先修改总览表中的开发排期或开始日期。",
        "",
    ])
    return section_lines


def replace_section(lines: list[str], section_range: tuple[int, int], new_section_lines: list[str]) -> list[str]:
    start_index, end_index = section_range
    return [*lines[:start_index], *new_section_lines, *lines[end_index:]]


def refresh_document(document: ScheduleDocument, recalculate_overview_dates: bool, schedule_owner: str) -> str:
    overview_rows = document.overview_rows
    if recalculate_overview_dates:
        overview_rows = allocate_completion_dates(overview_rows, document.start_date, document.skip_dates)

    lines = replace_section(document.lines, document.section_one_range, render_overview_section(overview_rows))

    refreshed_document = parse_schedule_document("\n".join(lines))
    owner = choose_schedule_owner(overview_rows, schedule_owner)
    daily_rows = build_daily_plan_rows(overview_rows, owner, document.skip_dates, document.start_date.year)
    lines = replace_section(lines, refreshed_document.section_three_range, render_section_three(daily_rows, document.skip_dates))
    return "\n".join(lines) + "\n"


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    markdown_text = input_path.read_text(encoding="utf-8")
    document = parse_schedule_document(markdown_text)
    refreshed_text = refresh_document(
        document=document,
        recalculate_overview_dates=args.recalculate_overview_dates,
        schedule_owner=args.schedule_owner,
    )

    if args.dry_run or not args.write:
        print(refreshed_text)
        return 0

    output_path = Path(args.output) if args.output else input_path
    output_path.write_text(refreshed_text, encoding="utf-8")
    print(f"Wrote refreshed schedule: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
