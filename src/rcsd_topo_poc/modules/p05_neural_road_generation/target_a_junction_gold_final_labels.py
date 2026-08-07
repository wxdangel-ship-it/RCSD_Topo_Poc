from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class JunctionGoldFinalVersionReview:
    case_id: str
    source_version_count: int
    terminal_signature_count: int
    status: str
    sample_ids: tuple[str, ...]
    terminal_business_signatures: tuple[str, ...]


def write_junction_gold_final_labels(
    *,
    base_labels_path: Path,
    t05_replay_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    labels = tuple(_read_jsonl(Path(base_labels_path)))
    replay_rows = tuple(_read_jsonl(Path(t05_replay_path)))
    replay_by_sample = {str(row["sample_id"]): row for row in replay_rows}
    if len(replay_by_sample) != len(replay_rows):
        raise ValueError("T05 replay contains duplicate sample_id values")

    final_labels = tuple(
        _finalize_label(label, replay_by_sample=replay_by_sample)
        for label in labels
    )
    accepted_sample_ids = {
        str(row["sample_id"])
        for row in labels
        if str(row.get("label_status")) == "READY"
        and str(row.get("surface_state")) == "accepted"
    }
    missing_replay_ids = sorted(accepted_sample_ids - set(replay_by_sample))
    extra_replay_ids = sorted(set(replay_by_sample) - accepted_sample_ids)
    if missing_replay_ids or extra_replay_ids:
        raise ValueError(
            "T05 replay coverage mismatch: "
            f"missing={len(missing_replay_ids)} extra={len(extra_replay_ids)}"
        )

    reviews = _version_reviews(final_labels)
    labels_path = output / "junction_gold_final_labels.jsonl"
    reviews_path = output / "junction_gold_final_version_reviews.jsonl"
    _write_jsonl(labels_path, final_labels)
    _write_jsonl(reviews_path, (asdict(row) for row in reviews))
    summary = {
        "schema_version": "p05-target-a-junction-gold-final-labels-v1",
        "status": (
            "JUNCTION_GOLD_FINAL_LABELS_GO"
            if not missing_replay_ids
            and not extra_replay_ids
            and all(str(row.get("label_status")) == "READY" for row in final_labels)
            else "JUNCTION_GOLD_FINAL_LABELS_REVIEW"
        ),
        "label_record_count": len(final_labels),
        "unique_case_id_count": len({str(row["case_id"]) for row in final_labels}),
        "accepted_surface_count": len(accepted_sample_ids),
        "t05_replay_count": len(replay_rows),
        "final_anchor_business_state_counts": _counts(
            row.get("anchor_business_state") for row in final_labels
        ),
        "t05_replay_status_counts": _counts(
            row.get("t05_replay_status") for row in final_labels
        ),
        "complete_junction_gold_status_counts": _counts(
            row.get("complete_junction_gold_status") for row in final_labels
        ),
        "junctionization_action_gold_status_counts": _counts(
            row.get("junctionization_action_gold_status") for row in final_labels
        ),
        "junctionization_scene_counts": _counts(
            row.get("junctionization_scene")
            for row in final_labels
            if row.get("junctionization_scene")
        ),
        "t05_consistency_failure_counts": _counts(
            failure
            for row in final_labels
            for failure in row.get("t05_consistency_failures", [])
        ),
        "source_version_review_count": len(reviews),
        "source_version_same_terminal_count": sum(
            row.status == "SAME_TERMINAL_BUSINESS" for row in reviews
        ),
        "source_version_conflicting_terminal_count": sum(
            row.status == "TERMINAL_BUSINESS_CONFLICT" for row in reviews
        ),
        "geometry_changed": False,
        "silent_fix": False,
        "artifacts": {
            "labels": _artifact(labels_path),
            "version_reviews": _artifact(reviews_path),
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _finalize_label(
    label: Mapping[str, Any],
    *,
    replay_by_sample: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    result = dict(label)
    result["pre_t05_anchor_business_state"] = str(
        label.get("anchor_business_state") or ""
    )
    surface_accepted = (
        str(label.get("label_status")) == "READY"
        and str(label.get("surface_state")) == "accepted"
    )
    if not surface_accepted:
        result.update(
            {
                "anchor_business_state": "QUALITY_ISSUE",
                "t05_replay_status": "NOT_APPLICABLE",
                "junctionization_scene": "",
                "junctionization_action": "",
                "junctionization_action_gold_status": "NOT_APPLICABLE",
                "complete_junction_gold_status": "READY",
                "selected_main_rcsdnode_id": "",
                "t05_original_rcsdroad_ids": [],
                "t05_new_rcsdroad_ids": [],
                "t05_original_rcsdnode_ids": [],
                "t05_new_rcsdnode_ids": [],
                "t05_grouped_rcsdnode_ids": [],
                "t05_consistency_failures": [],
                "t05_phase2_relation_path": "",
                "t05_phase2_rcsdroad_path": "",
                "t05_phase2_rcsdnode_path": "",
            }
        )
    else:
        replay = replay_by_sample.get(str(label["sample_id"]))
        if replay is None:
            raise ValueError(f"missing T05 replay for accepted surface: {label['sample_id']}")
        replay_status = str(replay.get("status") or "QUALITY_ISSUE")
        consistency_failures = _phase2_consistency_failures(replay)
        result.update(
            {
                "anchor_business_state": replay_status,
                "t05_replay_status": replay_status,
                "junctionization_scene": str(replay.get("scene") or ""),
                "junctionization_action": str(replay.get("action") or ""),
                "junctionization_action_gold_status": (
                    "READY"
                    if replay_status in {"SUCCESS", "NO_RCSD_EVIDENCE"}
                    else "ACTION_ONLY"
                ),
                "complete_junction_gold_status": (
                    "READY"
                    if replay_status in {"SUCCESS", "NO_RCSD_EVIDENCE"}
                    else "SAFETY_ONLY"
                ),
                "selected_main_rcsdnode_id": str(
                    replay.get("selected_main_rcsdnode_id") or ""
                ),
                "t05_original_rcsdroad_ids": _sorted_ids(
                    replay.get("original_rcsdroad_ids")
                ),
                "t05_new_rcsdroad_ids": _sorted_ids(replay.get("new_rcsdroad_ids")),
                "t05_original_rcsdnode_ids": _sorted_ids(
                    replay.get("original_rcsdnode_ids")
                ),
                "t05_new_rcsdnode_ids": _sorted_ids(replay.get("new_rcsdnode_ids")),
                "t05_grouped_rcsdnode_ids": _sorted_ids(
                    replay.get("grouped_rcsdnode_ids")
                ),
                "t05_consistency_failures": consistency_failures,
                "t05_phase2_relation_path": str(
                    replay.get("phase2_relation_path") or ""
                ),
                "t05_phase2_rcsdroad_path": str(
                    replay.get("phase2_rcsdroad_path") or ""
                ),
                "t05_phase2_rcsdnode_path": str(
                    replay.get("phase2_rcsdnode_path") or ""
                ),
            }
        )

    result["terminal_business_signature"] = _terminal_signature(result)
    return result


def _terminal_signature(row: Mapping[str, Any]) -> str:
    payload = {
        "t07_step1_has_evd": row.get("t07_step1_has_evd"),
        "t07_step2_is_anchor": row.get("t07_step2_is_anchor"),
        "surface_state": row.get("surface_state"),
        "surface_geometry_sha256": row.get("surface_geometry_sha256"),
        "relation_state": row.get("relation_state"),
        "anchor_business_state": row.get("anchor_business_state"),
        "selected_rcsd_node_ids": _sorted_ids(row.get("selected_rcsd_node_ids")),
        "selected_rcsd_road_ids": _sorted_ids(row.get("selected_rcsd_road_ids")),
        "support_rcsd_node_ids": _sorted_ids(row.get("support_rcsd_node_ids")),
        "support_rcsd_road_ids": _sorted_ids(row.get("support_rcsd_road_ids")),
        "route_class": row.get("route_class"),
        "junctionization_scene": row.get("junctionization_scene"),
        "junctionization_action": row.get("junctionization_action"),
        "selected_main_rcsdnode_id": row.get("selected_main_rcsdnode_id"),
        "t05_original_rcsdroad_ids": _sorted_ids(row.get("t05_original_rcsdroad_ids")),
        "t05_new_rcsdroad_ids": _sorted_ids(row.get("t05_new_rcsdroad_ids")),
        "t05_original_rcsdnode_ids": _sorted_ids(row.get("t05_original_rcsdnode_ids")),
        "t05_new_rcsdnode_ids": _sorted_ids(row.get("t05_new_rcsdnode_ids")),
        "t05_grouped_rcsdnode_ids": _sorted_ids(row.get("t05_grouped_rcsdnode_ids")),
        "t05_consistency_failures": sorted(
            str(value) for value in row.get("t05_consistency_failures", [])
        ),
        "complete_junction_gold_status": row.get("complete_junction_gold_status"),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _phase2_consistency_failures(replay: Mapping[str, Any]) -> list[str]:
    audit_path = str(replay.get("phase2_audit_path") or "")
    if not audit_path:
        return []
    summary_path = Path(audit_path).parent / "summary.json"
    if not summary_path.is_file():
        return ["phase2_summary_missing"]
    summary = _read_json(summary_path)
    consistency = summary.get("consistency") or {}
    return sorted(
        str(key)
        for key, value in consistency.items()
        if value is False and str(key) != "passed"
    )


def _version_reviews(
    labels: Iterable[Mapping[str, Any]],
) -> tuple[JunctionGoldFinalVersionReview, ...]:
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in labels:
        by_case[str(row["case_id"])].append(row)
    reviews: list[JunctionGoldFinalVersionReview] = []
    for case_id, rows in sorted(by_case.items()):
        if len(rows) <= 1:
            continue
        signatures = tuple(
            sorted({str(row["terminal_business_signature"]) for row in rows})
        )
        reviews.append(
            JunctionGoldFinalVersionReview(
                case_id=case_id,
                source_version_count=len(rows),
                terminal_signature_count=len(signatures),
                status=(
                    "SAME_TERMINAL_BUSINESS"
                    if len(signatures) == 1
                    else "TERMINAL_BUSINESS_CONFLICT"
                ),
                sample_ids=tuple(sorted(str(row["sample_id"]) for row in rows)),
                terminal_business_signatures=signatures,
            )
        )
    return tuple(reviews)


def _sorted_ids(values: Any) -> list[str]:
    if values in (None, ""):
        return []
    if isinstance(values, str):
        raw = values.replace(",", "|").split("|")
    else:
        raw = values
    return sorted({str(value).strip() for value in raw if str(value).strip()})


def _counts(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
