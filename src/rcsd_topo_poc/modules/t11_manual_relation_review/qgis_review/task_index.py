from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .excel_sync import XlsxRow, read_xlsx_rows


REVIEW_WORKBOOK_FILENAMES = {
    "all_evidence_relation_gaps": "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx",
    "no_evidence_relation_gaps": "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx",
}


@dataclass(frozen=True)
class ReviewTask:
    task_id: str
    source_table: str
    workbook_path: Path
    sheet_name: str
    excel_row: int
    row_order: int
    swsd_segment_id: str
    target_id: str
    segment_length_m: float
    segment_priority_rank: int | None
    segment_priority_bucket: str
    manual_relation_type: str
    selected_ids: str
    comment: str
    status: str
    raw: dict[str, str]


def load_review_tasks(workbook_paths: dict[str, Path] | Iterable[Path]) -> list[ReviewTask]:
    tasks: list[ReviewTask] = []
    for source_table, path in _iter_workbook_paths(workbook_paths):
        for row_order, row in enumerate(read_xlsx_rows(path), start=1):
            task = _row_to_task(source_table, row, row_order)
            if task is not None:
                tasks.append(task)
    sorted_tasks = sorted(tasks, key=_task_sort_key)
    seen: set[str] = set()
    deduped: list[ReviewTask] = []
    for task in sorted_tasks:
        if task.target_id in seen:
            continue
        seen.add(task.target_id)
        deduped.append(task)
    return deduped


def write_task_index_json(tasks: Iterable[ReviewTask], path: Path) -> None:
    payload = {
        "task_count": 0,
        "tasks": [],
    }
    for task in tasks:
        item = asdict(task)
        item["workbook_path"] = str(task.workbook_path)
        payload["tasks"].append(item)
    payload["task_count"] = len(payload["tasks"])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def infer_source_table(path: Path) -> str:
    name = Path(path).name
    for table_name, filename in REVIEW_WORKBOOK_FILENAMES.items():
        if name == filename:
            return table_name
    return Path(path).stem


def task_status(row: dict[str, str]) -> str:
    manual_type = _text(row.get("manual_relation_type"))
    selected_ids = _text(row.get("selected_ids"))
    comment = _text(row.get("comment"))
    if manual_type == "no_valid_relation" and selected_ids.upper() == "NULL":
        return "NULL"
    if manual_type == "uncertain":
        return "uncertain"
    if manual_type and selected_ids and selected_ids.upper() != "NULL":
        return "filled"
    if manual_type or selected_ids or comment:
        return "partial"
    return "blank"


def _iter_workbook_paths(workbook_paths: dict[str, Path] | Iterable[Path]) -> Iterable[tuple[str, Path]]:
    if isinstance(workbook_paths, dict):
        for source_table, path in workbook_paths.items():
            yield source_table, Path(path)
        return
    for path in workbook_paths:
        path = Path(path)
        yield infer_source_table(path), path


def _row_to_task(source_table: str, row: XlsxRow, row_order: int) -> ReviewTask | None:
    raw = row.values
    target_id = _text(raw.get("target_id"))
    if not target_id:
        return None
    if _is_false_like(raw.get("manual_row_consumable")):
        return None
    segment_id = _text(raw.get("swsd_segment_id"))
    rank = _int_or_none(raw.get("segment_priority_rank")) or _int_or_none(raw.get("segment_rank_by_length"))
    length = _float_or_zero(raw.get("segment_length_m"))
    return ReviewTask(
        task_id=f"{source_table}:{row.excel_row}:{target_id}",
        source_table=source_table,
        workbook_path=row.workbook_path,
        sheet_name=row.sheet_name,
        excel_row=row.excel_row,
        row_order=row_order,
        swsd_segment_id=segment_id,
        target_id=target_id,
        segment_length_m=length,
        segment_priority_rank=rank,
        segment_priority_bucket=_text(raw.get("segment_priority_bucket")),
        manual_relation_type=_text(raw.get("manual_relation_type")),
        selected_ids=_text(raw.get("selected_ids")),
        comment=_text(raw.get("comment")),
        status=task_status(raw),
        raw=dict(raw),
    )


def _task_sort_key(task: ReviewTask) -> tuple[Any, ...]:
    rank = task.segment_priority_rank if task.segment_priority_rank is not None else 10**12
    return (
        rank,
        task.segment_priority_bucket,
        -task.segment_length_m,
        task.swsd_segment_id,
        0 if task.source_table == "all_evidence_relation_gaps" else 1,
        task.row_order,
        task.target_id,
    )


def _is_false_like(value: Any) -> bool:
    text = _text(value).lower()
    return text in {"0", "false", "no", "n"}


def _int_or_none(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _float_or_zero(value: Any) -> float:
    try:
        return float(_text(value))
    except ValueError:
        return 0.0


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()
