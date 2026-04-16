from __future__ import annotations

import json
from pathlib import Path


def load_review_rows(results_root: Path) -> list[dict[str, object]]:
    review_index_path = results_root / "review_index.json"
    payload = json.loads(review_index_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("cases"), list):
            return list(payload["cases"])
        if isinstance(payload.get("rows"), list):
            return list(payload["rows"])
    raise ValueError(f"unexpected review_index payload shape: {review_index_path}")


def load_status_doc(results_root: Path, case_id: str) -> dict[str, object]:
    status_path = (
        results_root
        / "cases"
        / str(case_id)
        / "t02_virtual_intersection_poc_status.json"
    )
    return json.loads(status_path.read_text(encoding="utf-8"))


def build_kind2_4_cluster_rows(results_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for review_row in load_review_rows(results_root):
        case_id = str(review_row.get("case_id") or review_row.get("mainnodeid"))
        status_doc = load_status_doc(results_root, case_id)
        resolved_kind = status_doc.get("resolved_kind")
        kind_2 = status_doc.get("kind_2")
        if resolved_kind != 4 and kind_2 != 4:
            continue

        step6 = (((status_doc.get("stage3_audit_record") or {}).get("step6")) or {})
        rows.append(
            {
                "case_id": case_id,
                "acceptance_class": status_doc.get("acceptance_class"),
                "visual_review_class": status_doc.get("visual_review_class"),
                "root_cause_layer": status_doc.get("root_cause_layer"),
                "root_cause_type": status_doc.get("root_cause_type"),
                "status": status_doc.get("status"),
                "polygon_aspect_ratio": step6.get("polygon_aspect_ratio"),
                "polygon_compactness": step6.get("polygon_compactness"),
                "polygon_bbox_fill_ratio": step6.get("polygon_bbox_fill_ratio"),
                "bounded_regularization_applied": "bounded_regularization_applied"
                in (step6.get("optimizer_events") or []),
            }
        )
    return sorted(rows, key=lambda row: row["case_id"])


def build_kind2_4_cluster_markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# kind_2=4 Cluster Eval",
        "",
        "| case_id | acceptance_class | visual_review_class | root_cause_layer | root_cause_type | status | aspect_ratio | compactness | bbox_fill_ratio | bounded_regularization_applied |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {case_id} | {acceptance_class} | {visual_review_class} | {root_cause_layer} | {root_cause_type} | {status} | {polygon_aspect_ratio} | {polygon_compactness} | {polygon_bbox_fill_ratio} | {bounded_regularization_applied} |".format(
                **row
            )
        )
    return "\n".join(lines) + "\n"
