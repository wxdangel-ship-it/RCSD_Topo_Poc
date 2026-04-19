from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import sort_patch_key
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    Step67CaseResult,
    Step67ReviewIndexRow,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_observability import (
    write_json_atomic,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    feature_id,
    feature_mainnodeid,
)


T03_STREAMED_CASE_RESULTS_FILENAME = "t03_streamed_case_results.jsonl"
T03_TERMINAL_CASE_RECORDS_DIRNAME = "terminal_case_records"
VISUAL_V1 = "V1 认可成功"
VISUAL_V2 = "V2 业务正确但几何待修"
VISUAL_V3 = "V3 漏包 required"
VISUAL_V4 = "V4 误包 foreign"
VISUAL_V5 = "V5 明确失败"


@dataclass(frozen=True)
class T03StreamedCaseResult:
    case_id: str
    representative_node_id: str
    representative_mainnodeid: str
    template_class: str | None
    association_class: str
    step45_state: str
    step6_state: str
    step7_state: str
    visual_class: str
    reason: str
    note: str
    root_cause_layer: str | None
    root_cause_type: str | None
    source_png_path: str
    final_polygon_path: str


@dataclass(frozen=True)
class T03TerminalCaseRecord:
    case_id: str
    terminal_state: str
    representative_node_id: str
    representative_mainnodeid: str
    template_class: str | None
    association_class: str
    step45_state: str
    step6_state: str
    step7_state: str
    visual_class: str
    reason: str
    note: str
    root_cause_layer: str | None
    root_cause_type: str | None
    source_png_path: str
    final_polygon_path: str


def streamed_case_results_path(internal_root: Path) -> Path:
    return internal_root / T03_STREAMED_CASE_RESULTS_FILENAME


def terminal_case_records_root(internal_root: Path) -> Path:
    return internal_root / T03_TERMINAL_CASE_RECORDS_DIRNAME


def terminal_case_record_path(internal_root: Path, case_id: str) -> Path:
    return terminal_case_records_root(internal_root) / f"{case_id}.json"


def build_streamed_case_result(
    *,
    case_id: str,
    representative_feature,
    case_result: Step67CaseResult,
    review_row: Step67ReviewIndexRow,
    run_root: Path,
) -> T03StreamedCaseResult:
    representative_node_id = feature_id(representative_feature) or case_id
    representative_mainnodeid = feature_mainnodeid(representative_feature) or representative_node_id
    return T03StreamedCaseResult(
        case_id=case_id,
        representative_node_id=representative_node_id,
        representative_mainnodeid=representative_mainnodeid,
        template_class=case_result.template_class,
        association_class=case_result.association_class,
        step45_state=case_result.step45_state,
        step6_state=case_result.step6_result.step6_state,
        step7_state=case_result.step7_result.step7_state,
        visual_class=case_result.step7_result.visual_review_class,
        reason=case_result.step7_result.reason,
        note=case_result.step7_result.note or "",
        root_cause_layer=case_result.step7_result.root_cause_layer,
        root_cause_type=case_result.step7_result.root_cause_type,
        source_png_path=review_row.source_png_path,
        final_polygon_path=str(run_root / "cases" / case_id / "step67_final_polygon.gpkg"),
    )


def terminal_case_record_from_streamed_result(
    record: T03StreamedCaseResult,
    *,
    terminal_state: str | None = None,
) -> T03TerminalCaseRecord:
    resolved_terminal_state = str(terminal_state or record.step7_state)
    return T03TerminalCaseRecord(
        case_id=record.case_id,
        terminal_state=resolved_terminal_state,
        representative_node_id=record.representative_node_id,
        representative_mainnodeid=record.representative_mainnodeid,
        template_class=record.template_class,
        association_class=record.association_class,
        step45_state=record.step45_state,
        step6_state=record.step6_state,
        step7_state=record.step7_state,
        visual_class=record.visual_class,
        reason=record.reason,
        note=record.note,
        root_cause_layer=record.root_cause_layer,
        root_cause_type=record.root_cause_type,
        source_png_path=record.source_png_path,
        final_polygon_path=record.final_polygon_path,
    )


def build_terminal_case_record(
    *,
    case_id: str,
    representative_feature,
    case_result: Step67CaseResult,
    review_row: Step67ReviewIndexRow,
    run_root: Path,
) -> T03TerminalCaseRecord:
    return terminal_case_record_from_streamed_result(
        build_streamed_case_result(
            case_id=case_id,
            representative_feature=representative_feature,
            case_result=case_result,
            review_row=review_row,
            run_root=run_root,
        ),
        terminal_state=case_result.step7_result.step7_state,
    )


def build_runtime_failed_terminal_case_record(
    *,
    case_id: str,
    representative_feature,
    reason: str,
    detail: str,
) -> T03TerminalCaseRecord:
    representative_node_id = feature_id(representative_feature) or case_id
    representative_mainnodeid = feature_mainnodeid(representative_feature) or representative_node_id
    return T03TerminalCaseRecord(
        case_id=case_id,
        terminal_state="runtime_failed",
        representative_node_id=representative_node_id,
        representative_mainnodeid=representative_mainnodeid,
        template_class=None,
        association_class="",
        step45_state="",
        step6_state="",
        step7_state="runtime_failed",
        visual_class=VISUAL_V5,
        reason=str(reason or "runtime_failed"),
        note=str(detail or ""),
        root_cause_layer="runtime",
        root_cause_type="runtime_failed",
        source_png_path="",
        final_polygon_path="",
    )


def streamed_case_result_from_terminal_record(
    record: T03TerminalCaseRecord,
) -> T03StreamedCaseResult | None:
    if record.terminal_state not in {"accepted", "rejected"}:
        return None
    return T03StreamedCaseResult(
        case_id=record.case_id,
        representative_node_id=record.representative_node_id,
        representative_mainnodeid=record.representative_mainnodeid,
        template_class=record.template_class,
        association_class=record.association_class,
        step45_state=record.step45_state,
        step6_state=record.step6_state,
        step7_state=record.step7_state,
        visual_class=record.visual_class,
        reason=record.reason,
        note=record.note,
        root_cause_layer=record.root_cause_layer,
        root_cause_type=record.root_cause_type,
        source_png_path=record.source_png_path,
        final_polygon_path=record.final_polygon_path,
    )


def append_streamed_case_result(path: Path, record: T03StreamedCaseResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_streamed_case_results(path: Path) -> dict[str, T03StreamedCaseResult]:
    if not path.is_file():
        return {}
    records_by_case_id: dict[str, T03StreamedCaseResult] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, raw_line in enumerate(lines):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
        record = T03StreamedCaseResult(**payload)
        records_by_case_id[record.case_id] = record
    return {
        case_id: records_by_case_id[case_id]
        for case_id in sorted(records_by_case_id, key=sort_patch_key)
    }


def write_terminal_case_record(
    *,
    internal_root: Path,
    record: T03TerminalCaseRecord,
) -> Path:
    path = terminal_case_record_path(internal_root, record.case_id)
    write_json_atomic(path, asdict(record))
    return path


def load_terminal_case_records(internal_root: Path) -> dict[str, T03TerminalCaseRecord]:
    root = terminal_case_records_root(internal_root)
    if not root.is_dir():
        return {}
    records: dict[str, T03TerminalCaseRecord] = {}
    for path in sorted(root.glob("*.json"), key=lambda item: sort_patch_key(item.stem)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = T03TerminalCaseRecord(**payload)
        except Exception:
            continue
        records[record.case_id] = record
    return {
        case_id: records[case_id]
        for case_id in sorted(records, key=sort_patch_key)
    }


def reconstruct_streamed_case_result_from_case_outputs(
    *,
    run_root: Path,
    case_id: str,
) -> T03StreamedCaseResult | None:
    case_dir = run_root / "cases" / case_id
    final_polygon_path = case_dir / "step67_final_polygon.gpkg"
    review_png_path = case_dir / "step67_review.png"
    step6_status_path = case_dir / "step6_status.json"
    step7_status_path = case_dir / "step7_status.json"
    if not (final_polygon_path.is_file() and step6_status_path.is_file() and step7_status_path.is_file()):
        return None

    step6_status = json.loads(step6_status_path.read_text(encoding="utf-8"))
    step7_status = json.loads(step7_status_path.read_text(encoding="utf-8"))
    return T03StreamedCaseResult(
        case_id=case_id,
        representative_node_id=case_id,
        representative_mainnodeid=case_id,
        template_class=step7_status.get("template_class"),
        association_class=str(step7_status.get("association_class") or ""),
        step45_state=str(step7_status.get("step45_state") or ""),
        step6_state=str(step6_status.get("step6_state") or ""),
        step7_state=str(step7_status.get("step7_state") or ""),
        visual_class=_infer_visual_class(step6_status=step6_status, step7_status=step7_status),
        reason=str(step7_status.get("reason") or ""),
        note=str(step7_status.get("note") or ""),
        root_cause_layer=step7_status.get("root_cause_layer"),
        root_cause_type=step7_status.get("root_cause_type"),
        source_png_path=str(review_png_path) if review_png_path.is_file() else "",
        final_polygon_path=str(final_polygon_path),
    )


def reconstruct_terminal_case_record_from_case_outputs(
    *,
    run_root: Path,
    case_id: str,
) -> T03TerminalCaseRecord | None:
    streamed_result = reconstruct_streamed_case_result_from_case_outputs(
        run_root=run_root,
        case_id=case_id,
    )
    if streamed_result is None:
        return None
    return terminal_case_record_from_streamed_result(
        streamed_result,
        terminal_state=streamed_result.step7_state,
    )


def load_closeout_case_results(
    *,
    internal_root: Path,
    run_root: Path,
    case_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, T03StreamedCaseResult]:
    terminal_records = load_terminal_case_records(internal_root)
    streamed_results = load_streamed_case_results(streamed_case_results_path(internal_root))
    ordered_case_ids: list[str]
    if case_ids is None:
        discovered_case_ids = set(terminal_records.keys()) | set(streamed_results.keys())
        cases_dir = run_root / "cases"
        if cases_dir.is_dir():
            discovered_case_ids.update(
                path.name
                for path in cases_dir.iterdir()
                if path.is_dir()
            )
        ordered_case_ids = sorted(
            discovered_case_ids,
            key=sort_patch_key,
        )
    else:
        ordered_case_ids = sorted([str(case_id) for case_id in case_ids], key=sort_patch_key)

    resolved: dict[str, T03StreamedCaseResult] = {}
    for case_id in ordered_case_ids:
        terminal_record = terminal_records.get(case_id)
        terminal_streamed = (
            streamed_case_result_from_terminal_record(terminal_record)
            if terminal_record is not None
            else None
        )
        if terminal_streamed is not None:
            resolved[case_id] = terminal_streamed
            continue
        streamed_record = streamed_results.get(case_id)
        if streamed_record is not None and streamed_record.step7_state in {"accepted", "rejected"}:
            resolved[case_id] = streamed_record
            continue
        reconstructed = reconstruct_streamed_case_result_from_case_outputs(
            run_root=run_root,
            case_id=case_id,
        )
        if reconstructed is not None:
            resolved[case_id] = reconstructed
    return {
        case_id: resolved[case_id]
        for case_id in sorted(resolved, key=sort_patch_key)
    }


def _infer_visual_class(
    *,
    step6_status: dict[str, Any],
    step7_status: dict[str, Any],
) -> str:
    step7_state = str(step7_status.get("step7_state") or "")
    reason = str(step7_status.get("reason") or "")
    if step7_state == "accepted":
        if reason in {
            "step67_accepted_with_upstream_step3_visual_risk",
            "step67_accepted_with_visual_risk",
        }:
            return VISUAL_V2
        return VISUAL_V1

    if str(step7_status.get("step45_state") or "") == "not_established":
        return VISUAL_V5
    if not bool(step6_status.get("geometry_established")):
        secondary_root_cause = str(step6_status.get("secondary_root_cause") or "")
        if secondary_root_cause == "stage3_rc_gap":
            return VISUAL_V3
        if "foreign" in secondary_root_cause:
            return VISUAL_V4
    return VISUAL_V5


__all__ = [
    "T03_STREAMED_CASE_RESULTS_FILENAME",
    "T03_TERMINAL_CASE_RECORDS_DIRNAME",
    "T03StreamedCaseResult",
    "T03TerminalCaseRecord",
    "append_streamed_case_result",
    "build_runtime_failed_terminal_case_record",
    "build_streamed_case_result",
    "build_terminal_case_record",
    "load_closeout_case_results",
    "load_streamed_case_results",
    "load_terminal_case_records",
    "reconstruct_terminal_case_record_from_case_outputs",
    "reconstruct_streamed_case_result_from_case_outputs",
    "streamed_case_result_from_terminal_record",
    "streamed_case_results_path",
    "terminal_case_record_from_streamed_result",
    "terminal_case_record_path",
    "terminal_case_records_root",
    "write_terminal_case_record",
]
