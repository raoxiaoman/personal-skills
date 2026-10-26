from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ScheduleRow:
    version_label: str
    priority: str
    task: str
    product_owner: str
    product_progress: str
    dev_owner: str
    dev_estimate: str
    qa_owner: str
    qa_progress: str
    release_time: str
    remark: str


@dataclass(slots=True)
class SchedulePayload:
    version: str
    feature: str
    sheet_name: str
    start_cell: str
    rows: list[ScheduleRow]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchedulePayload":
        rows = [ScheduleRow(**row) for row in data["rows"]]
        return cls(
            version=data["version"],
            feature=data["feature"],
            sheet_name=data["sheet_name"],
            start_cell=data["start_cell"],
            rows=rows,
        )

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> "SchedulePayload":
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def write_json_file(self, file_path: str | Path) -> None:
        Path(file_path).write_text(self.to_json(), encoding="utf-8")


def rows_to_tsv(rows: list[ScheduleRow]) -> str:
    return "\n".join(
        "\t".join(
            [
                row.version_label,
                row.priority,
                row.task,
                row.product_owner,
                row.product_progress,
                row.dev_owner,
                row.dev_estimate,
                row.qa_owner,
                row.qa_progress,
                row.release_time,
                row.remark,
            ]
        )
        for row in rows
    )