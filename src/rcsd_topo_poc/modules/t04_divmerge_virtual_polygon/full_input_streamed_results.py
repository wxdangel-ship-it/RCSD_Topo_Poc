from __future__ import annotations

import csv
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import sort_patch_key

from .final_publish import STEP7_CASE_FINAL_REVIEW_NAME, T04Step7CaseArtifact
from .full_input_observability import write_json_atomic


T04_STREAMED_CASE_RESULTS_FILENAME = "t04_streamed_case_results.jsonl"
T04_TERMINAL_CASE_RECORDS_DIRNAME = "terminal_case_records"

FINAL_INDEX_FIELDNAMES = [
    "sequence_no",
    "case_id",
    "final_state",
    "image_path",
    "state_image_path",
    "step7_status_path",
    "audit_path",
    "reject_reason",
]


@dataclass(frozen=True)
class T04TerminalCaseRecord:
    case_id: str
    terminal_state: str
    final_state: str
    reject_reason: str
    reject_reason_detail: str
    step7_status_path: str
    audit_path: str
    source_image_path: str


def streamed_case_results_path(run_root: Path) -> Path:
    return run_root / T04_STREAMED_CASE_RESULTS_FILENAME


def terminal_case_records_root(run_root: Path) -> Path:
    return run_root / T04_TERMINAL_CASE_RECORDS_DIRNAME


def terminal_case_record_path(run_root: Path, case_id: str) -> Path:
    return terminal_case_records_root(run_root) / f"{case_id}.json"


def terminal_case_record_from_artifact(
    *,
    run_root: Path,
    artifact: T04Step7CaseArtifact,
) -> T04TerminalCaseRecord:
    case_dir = run_root / "cases" / artifact.case_id
    return T04TerminalCaseRecord(
        case_id=artifact.case_id,
        terminal_state=artifact.final_state,
        final_state=artifact.final_state,
        reject_reason=str(artifact.reject_reasons[0]) if artifact.reject_reasons else "",
        reject_reason_detail="|".join(artifact.reject_reasons),
        step7_status_path=str(case_dir / "step7_status.json"),
        audit_path=str(case_dir / "step7_audit.json"),
        source_image_path=str(case_dir / STEP7_CASE_FINAL_REVIEW_NAME),
    )


def runtime_failed_terminal_case_record(
    *,
    run_root: Path,
    case_id: str,
    reason: str,
    detail: str,
) -> T04TerminalCaseRecord:
    case_dir = run_root / "cases" / str(case_id)
    return T04TerminalCaseRecord(
        case_id=str(case_id),
        terminal_state="runtime_failed",
        final_state="",
        reject_reason=str(reason or "runtime_failed"),
        reject_reason_detail=str(detail or reason or "runtime_failed"),
        step7_status_path=str(case_dir / "step7_status.json"),
        audit_path=str(case_dir / "step7_audit.json"),
        source_image_path=str(case_dir / STEP7_CASE_FINAL_REVIEW_NAME),
    )


def append_streamed_case_result(path: Path, record: T04TerminalCaseRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_terminal_case_record(*, run_root: Path, record: T04TerminalCaseRecord) -> Path:
    path = terminal_case_record_path(run_root, record.case_id)
    write_json_atomic(path, asdict(record))
    return path


def load_terminal_case_records(run_root: Path) -> dict[str, T04TerminalCaseRecord]:
    root = terminal_case_records_root(run_root)
    if not root.is_dir():
        return {}
    records: dict[str, T04TerminalCaseRecord] = {}
    for path in sorted(root.glob("*.json"), key=lambda item: sort_patch_key(item.stem)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = T04TerminalCaseRecord(**payload)
        except Exception:
            continue
        records[record.case_id] = record
    return records


def _copy_if_present(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination)
    return str(destination)


def materialize_streamed_case_visual_check(
    *,
    run_root: Path,
    record: T04TerminalCaseRecord,
    visual_check_dir: Path | None = None,
) -> dict[str, Any]:
    visual_root = visual_check_dir or (run_root / "visual_checks")
    final_state = str(record.final_state or record.terminal_state or "unknown")
    image_name = f"case__{record.case_id}__{final_state}.png"
    source_image = Path(record.source_image_path) if record.source_image_path else (
        run_root / "cases" / record.case_id / STEP7_CASE_FINAL_REVIEW_NAME
    )
    if not source_image.is_file():
        return {
            "case_id": record.case_id,
            "final_state": final_state,
            "copied": False,
            "source_image_path": str(source_image),
        }

    step4_flat_image = run_root / "step4_review_flat" / f"case__{record.case_id}__final_review.png"
    visual_flat_image = visual_root / "final_flat" / image_name
    state_image = visual_root / "final_by_state" / final_state / image_name
    for target_path in (step4_flat_image, visual_flat_image, state_image):
        target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_image, step4_flat_image)
    shutil.copy2(source_image, visual_flat_image)
    shutil.copy2(source_image, state_image)
    return {
        "case_id": record.case_id,
        "final_state": final_state,
        "copied": True,
        "source_image_path": str(source_image),
        "step4_flat_image_path": str(step4_flat_image),
        "visual_flat_image_path": str(visual_flat_image),
        "state_image_path": str(state_image),
    }


def materialize_final_visual_checks(
    *,
    run_root: Path,
    artifacts: list[T04Step7CaseArtifact],
    visual_check_dir: Path | None = None,
) -> dict[str, Any]:
    visual_root = visual_check_dir or (run_root / "visual_checks")
    final_flat = visual_root / "final_flat"
    accepted_dir = visual_root / "final_by_state" / "accepted"
    rejected_dir = visual_root / "final_by_state" / "rejected"
    for target_dir in (final_flat, accepted_dir, rejected_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
        for png_path in target_dir.glob("*.png"):
            png_path.unlink()

    rows: list[dict[str, Any]] = []
    ordered = sorted(artifacts, key=lambda item: sort_patch_key(item.case_id))
    for sequence_no, artifact in enumerate(ordered, start=1):
        final_state = artifact.final_state
        image_name = f"{sequence_no:04d}__{artifact.case_id}__{final_state}.png"
        source_image = run_root / "cases" / artifact.case_id / STEP7_CASE_FINAL_REVIEW_NAME
        flat_image = final_flat / image_name
        state_dir = accepted_dir if final_state == "accepted" else rejected_dir
        state_image = state_dir / image_name
        _copy_if_present(source_image, flat_image)
        _copy_if_present(source_image, state_image)
        row = {
            "sequence_no": sequence_no,
            "case_id": artifact.case_id,
            "final_state": final_state,
            "image_path": str(flat_image),
            "state_image_path": str(state_image),
            "step7_status_path": str(run_root / "cases" / artifact.case_id / "step7_status.json"),
            "audit_path": str(run_root / "cases" / artifact.case_id / "step7_audit.json"),
            "reject_reason": str(artifact.reject_reasons[0]) if artifact.reject_reasons else "",
        }
        rows.append(row)

    index_csv_path = visual_root / "final_index.csv"
    with index_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FINAL_INDEX_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    index_json_path = visual_root / "final_index.json"
    write_json_atomic(
        index_json_path,
        {
            "row_count": len(rows),
            "accepted_count": sum(1 for row in rows if row["final_state"] == "accepted"),
            "rejected_count": sum(1 for row in rows if row["final_state"] == "rejected"),
            "rows": rows,
        },
    )
    return {
        "visual_check_dir": str(visual_root),
        "final_flat_dir": str(final_flat),
        "final_by_state_accepted_dir": str(accepted_dir),
        "final_by_state_rejected_dir": str(rejected_dir),
        "final_index_csv_path": str(index_csv_path),
        "final_index_json_path": str(index_json_path),
        "final_flat_png_count": len(list(final_flat.glob("*.png"))),
        "accepted_png_count": len(list(accepted_dir.glob("*.png"))),
        "rejected_png_count": len(list(rejected_dir.glob("*.png"))),
    }


__all__ = [
    "T04TerminalCaseRecord",
    "append_streamed_case_result",
    "load_terminal_case_records",
    "materialize_final_visual_checks",
    "materialize_streamed_case_visual_check",
    "runtime_failed_terminal_case_record",
    "streamed_case_results_path",
    "terminal_case_record_from_artifact",
    "write_terminal_case_record",
]
