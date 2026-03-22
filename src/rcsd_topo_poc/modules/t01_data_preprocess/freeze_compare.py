from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _find_repo_root
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    ROAD_S_GRADE_FIELD,
    get_road_segmentid,
    get_road_sgrade,
)


CURRENT_MANIFEST_NAME = "skill_v1_manifest.json"
CURRENT_SUMMARY_NAME = "skill_v1_summary.json"
CURRENT_VALIDATED_NAME = "validated_pairs_skill_v1.csv"
CURRENT_SEGMENT_BODY_NAME = "segment_body_membership_skill_v1.csv"
CURRENT_TRUNK_NAME = "trunk_membership_skill_v1.csv"
CURRENT_NODES_HASH_NAME = "refreshed_nodes_hash.json"
CURRENT_ROADS_HASH_NAME = "refreshed_roads_hash.json"

BASELINE_MANIFEST_NAME = "FREEZE_MANIFEST.json"
BASELINE_SUMMARY_NAME = "FREEZE_SUMMARY.json"
BASELINE_RULES_NAME = "FREEZE_COMPARE_RULES.md"
BASELINE_VALIDATED_NAME = "validated_pairs_baseline.csv"
BASELINE_SEGMENT_BODY_NAME = "segment_body_membership_baseline.csv"
BASELINE_TRUNK_NAME = "trunk_membership_baseline.csv"
BASELINE_NODES_HASH_NAME = "refreshed_nodes_hash.json"
BASELINE_ROADS_HASH_NAME = "refreshed_roads_hash.json"


def _artifact_name(mode: Literal["current", "baseline"], artifact: str) -> str:
    mapping = {
        "current": {
            "manifest": CURRENT_MANIFEST_NAME,
            "summary": CURRENT_SUMMARY_NAME,
            "validated_pairs": CURRENT_VALIDATED_NAME,
            "segment_body_membership": CURRENT_SEGMENT_BODY_NAME,
            "trunk_membership": CURRENT_TRUNK_NAME,
            "nodes_hash": CURRENT_NODES_HASH_NAME,
            "roads_hash": CURRENT_ROADS_HASH_NAME,
        },
        "baseline": {
            "manifest": BASELINE_MANIFEST_NAME,
            "summary": BASELINE_SUMMARY_NAME,
            "validated_pairs": BASELINE_VALIDATED_NAME,
            "segment_body_membership": BASELINE_SEGMENT_BODY_NAME,
            "trunk_membership": BASELINE_TRUNK_NAME,
            "nodes_hash": BASELINE_NODES_HASH_NAME,
            "roads_hash": BASELINE_ROADS_HASH_NAME,
        },
    }
    return mapping[mode][artifact]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _load_geojson(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_payload(path: Path) -> dict[str, Any]:
    return {
        "file_name": path.name,
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _load_json_if_exists(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonicalize_geojson_feature(*, feature: dict[str, Any], kind: Literal["nodes", "roads"]) -> dict[str, Any]:
    props = dict(feature.get("properties") or {})
    if kind == "roads":
        props[ROAD_S_GRADE_FIELD] = get_road_sgrade(props)
        props["segmentid"] = get_road_segmentid(props)
        props.pop("s_grade", None)
        props.pop("segment_id", None)
        props.pop("Segment_id", None)
    else:
        props.pop("s_grade", None)
        props.pop(ROAD_S_GRADE_FIELD, None)
        props.pop("segment_id", None)
        props.pop("Segment_id", None)
        props.pop("segmentid", None)
        props.pop("working_mainnodeid", None)
    return {
        "properties": props,
        "geometry": feature.get("geometry"),
    }


def _semantic_geojson_hash(path: Path, *, kind: Literal["nodes", "roads"]) -> str:
    doc = _load_geojson(path)
    canonical_features = [
        _canonicalize_geojson_feature(feature=feature, kind=kind)
        for feature in doc.get("features", [])
    ]
    canonical_features.sort(
        key=lambda feature: (
            str((feature.get("properties") or {}).get("id") or ""),
            json.dumps(feature.get("geometry"), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    )
    payload = {
        "type": "FeatureCollection",
        "features": canonical_features,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _manifest_source_path_candidates(source_path: str) -> list[Path]:
    candidates: list[Path] = []

    def _append(candidate: Path) -> None:
        if candidate not in candidates:
            candidates.append(candidate)

    _append(Path(str(source_path)))
    normalized = str(source_path).replace("\\", "/")
    if normalized.startswith("/mnt/"):
        parts = normalized.split("/")
        if len(parts) >= 4 and len(parts[2]) == 1:
            drive_letter = parts[2].upper()
            tail = "\\".join(parts[3:])
            _append(Path(f"{drive_letter}:\\{tail}"))
    elif len(normalized) >= 2 and normalized[1] == ":":
        drive_letter = normalized[0].lower()
        tail = normalized[2:].lstrip("/").replace("\\", "/")
        _append(Path(f"/mnt/{drive_letter}/{tail}"))

    return candidates


def _resolve_manifest_source_path(bundle_dir: Path, *, mode: Literal["current", "baseline"], artifact_key: str) -> Optional[Path]:
    manifest_path = bundle_dir / _artifact_name(mode, "manifest")
    manifest = _load_json_if_exists(manifest_path)
    if not manifest:
        return None
    source_paths = manifest.get("source_paths") or {}
    source_path = source_paths.get(artifact_key)
    if not source_path:
        return None
    for candidate in _manifest_source_path_candidates(str(source_path)):
        if candidate.is_file():
            return candidate
    return None


def _compare_hash_payloads(
    *,
    label: str,
    kind: Literal["nodes", "roads"],
    current_dir: Path,
    freeze_dir: Path,
    current_hash: dict[str, Any],
    baseline_hash: dict[str, Any],
) -> dict[str, Any]:
    current_source = _resolve_manifest_source_path(current_dir, mode="current", artifact_key=f"refreshed_{kind}_path")
    baseline_source = _resolve_manifest_source_path(freeze_dir, mode="baseline", artifact_key=f"refreshed_{kind}_path")
    semantic_hash_match = False
    semantic_compare_available = current_source is not None and baseline_source is not None
    if semantic_compare_available:
        semantic_hash_match = (
            _semantic_geojson_hash(current_source, kind=kind) == _semantic_geojson_hash(baseline_source, kind=kind)
        )

    raw_hash_match = current_hash.get("sha256") == baseline_hash.get("sha256")
    if raw_hash_match:
        status = "PASS"
        difference_type = None
    elif semantic_compare_available and semantic_hash_match:
        status = "SCHEMA_MIGRATION_DIFFERENCE"
        difference_type = "schema_migration_difference"
    else:
        status = "FAIL"
        difference_type = None

    return {
        "label": label,
        "status": status,
        "difference_type": difference_type,
        "current_sha256": current_hash.get("sha256"),
        "baseline_sha256": baseline_hash.get("sha256"),
        "semantic_compare_available": semantic_compare_available,
        "current_source_path": str(current_source.resolve()) if current_source is not None else None,
        "baseline_source_path": str(baseline_source.resolve()) if baseline_source is not None else None,
    }


def _road_ids_from_props(props: dict[str, Any]) -> list[str]:
    road_ids = props.get("road_ids")
    if isinstance(road_ids, list):
        return [str(value) for value in road_ids]
    road_ids_text = props.get("road_ids_text")
    if isinstance(road_ids_text, str) and road_ids_text.strip():
        return [part.strip() for part in road_ids_text.split(",") if part.strip()]
    return []


def _membership_rows(path: Path, *, stage: str, layer_role: str, prefer_feature_phase: bool = False) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    for feature in _load_geojson(path).get("features", []):
        props = feature.get("properties", {})
        pair_id = str(props.get("pair_id") or "")
        trunk_mode = str(props.get("trunk_mode") or "")
        row_stage = str(props.get("step5_phase") or stage) if prefer_feature_phase else stage
        for road_id in _road_ids_from_props(props):
            rows.append(
                {
                    "stage": row_stage,
                    "pair_id": pair_id,
                    "road_id": road_id,
                    "layer_role": layer_role,
                    "trunk_mode": trunk_mode,
                }
            )
    return sorted(rows, key=lambda row: tuple(row.get(key, "") for key in ("stage", "pair_id", "road_id", "layer_role")))


def _first_existing(base_dir: Path, *relative_paths: str) -> Optional[Path]:
    for relative_path in relative_paths:
        candidate = base_dir / relative_path
        if candidate.is_file():
            return candidate
    return None


def _validated_pair_rows(step2_dir: Path, step4_dir: Path, step5_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for source_path, stage in (
        (step2_dir / "validated_pairs.csv", "Step2"),
        (_first_existing(step4_dir, "step4_validated_pairs.csv", "STEP4/validated_pairs.csv"), "Step4"),
        (_first_existing(step5_dir, "step5_validated_pairs_merged.csv"), "Step5"),
    ):
        if source_path is None or not source_path.is_file():
            continue
        for row in _read_csv_rows(source_path):
            rows.append(
                {
                    "stage": stage,
                    "pair_id": str(row.get("pair_id") or ""),
                    "a_node_id": str(row.get("a_node_id") or ""),
                    "b_node_id": str(row.get("b_node_id") or ""),
                    "trunk_mode": str(row.get("trunk_mode") or ""),
                    "left_turn_excluded_mode": str(row.get("left_turn_excluded_mode") or ""),
                    "segment_body_road_count": str(row.get("segment_body_road_count") or ""),
                    "residual_road_count": str(row.get("residual_road_count") or ""),
                }
            )

    return sorted(rows, key=lambda row: tuple(row.get(key, "") for key in ("stage", "pair_id", "a_node_id", "b_node_id")))


def _compare_row_sets(*, current_rows: list[dict[str, str]], baseline_rows: list[dict[str, str]], label: str) -> dict[str, Any]:
    def _canonicalize(row: dict[str, str]) -> dict[str, str]:
        canonical = dict(row)
        stage = canonical.get("stage", "")
        if stage.lower().startswith("step5"):
            canonical["stage"] = stage.upper()
        return canonical

    current_set = {json.dumps(_canonicalize(row), ensure_ascii=False, sort_keys=True) for row in current_rows}
    baseline_set = {json.dumps(_canonicalize(row), ensure_ascii=False, sort_keys=True) for row in baseline_rows}
    only_current = sorted(current_set - baseline_set)
    only_baseline = sorted(baseline_set - current_set)
    return {
        "label": label,
        "status": "PASS" if not only_current and not only_baseline else "FAIL",
        "current_count": len(current_rows),
        "baseline_count": len(baseline_rows),
        "only_in_current_sample": [json.loads(value) for value in only_current[:20]],
        "only_in_baseline_sample": [json.loads(value) for value in only_baseline[:20]],
    }


def write_skill_v1_bundle(
    *,
    out_dir: Union[str, Path],
    step2_dir: Union[str, Path],
    step4_dir: Union[str, Path],
    step5_dir: Union[str, Path],
    refreshed_nodes_path: Union[str, Path],
    refreshed_roads_path: Union[str, Path],
    mode: Literal["current", "baseline"] = "current",
    skill_version: str = "1.0.0",
    freeze_label: Optional[str] = None,
) -> dict[str, Any]:
    resolved_out_dir = Path(out_dir)
    resolved_out_dir.mkdir(parents=True, exist_ok=True)
    step2_dir = Path(step2_dir)
    step4_dir = Path(step4_dir)
    step5_dir = Path(step5_dir)
    refreshed_nodes_path = Path(refreshed_nodes_path)
    refreshed_roads_path = Path(refreshed_roads_path)

    validated_rows = _validated_pair_rows(step2_dir, step4_dir, step5_dir)
    segment_body_rows = _membership_rows(step2_dir / "segment_body_roads.geojson", stage="Step2", layer_role="segment_body")
    segment_body_rows += _membership_rows(
        _first_existing(step4_dir, "step4_segment_body_roads.geojson", "STEP4/segment_body_roads.geojson") or step4_dir / "missing.geojson",
        stage="Step4",
        layer_role="segment_body",
    )
    step5_merged_segment_path = _first_existing(step5_dir, "step5_segment_body_roads_merged.geojson")
    if step5_merged_segment_path is not None:
        segment_body_rows += _membership_rows(
            step5_merged_segment_path,
            stage="Step5",
            layer_role="segment_body",
            prefer_feature_phase=True,
        )
    else:
        segment_body_rows += _membership_rows(
            _first_existing(step5_dir, "step5a_segment_body_roads.geojson", "STEP5A/segment_body_roads.geojson") or step5_dir / "missing.geojson",
            stage="Step5A",
            layer_role="segment_body",
        )
        segment_body_rows += _membership_rows(
            _first_existing(step5_dir, "step5b_segment_body_roads.geojson", "STEP5B/segment_body_roads.geojson") or step5_dir / "missing.geojson",
            stage="Step5B",
            layer_role="segment_body",
        )
        segment_body_rows += _membership_rows(
            _first_existing(step5_dir, "step5c_segment_body_roads.geojson", "STEP5C/segment_body_roads.geojson") or step5_dir / "missing.geojson",
            stage="Step5C",
            layer_role="segment_body",
        )

    trunk_rows = _membership_rows(step2_dir / "trunk_roads.geojson", stage="Step2", layer_role="trunk")
    trunk_rows += _membership_rows(
        _first_existing(step4_dir, "step4_trunk_roads.geojson", "STEP4/trunk_roads.geojson") or step4_dir / "missing.geojson",
        stage="Step4",
        layer_role="trunk",
    )
    trunk_rows += _membership_rows(
        _first_existing(step5_dir, "step5a_trunk_roads.geojson", "STEP5A/trunk_roads.geojson") or step5_dir / "missing.geojson",
        stage="Step5A",
        layer_role="trunk",
    )
    trunk_rows += _membership_rows(
        _first_existing(step5_dir, "step5b_trunk_roads.geojson", "STEP5B/trunk_roads.geojson") or step5_dir / "missing.geojson",
        stage="Step5B",
        layer_role="trunk",
    )
    trunk_rows += _membership_rows(
        _first_existing(step5_dir, "step5c_trunk_roads.geojson", "STEP5C/trunk_roads.geojson") or step5_dir / "missing.geojson",
        stage="Step5C",
        layer_role="trunk",
    )

    segment_body_rows = sorted(segment_body_rows, key=lambda row: tuple(row.get(key, "") for key in ("stage", "pair_id", "road_id")))
    trunk_rows = sorted(trunk_rows, key=lambda row: tuple(row.get(key, "") for key in ("stage", "pair_id", "road_id")))

    validated_path = resolved_out_dir / _artifact_name(mode, "validated_pairs")
    segment_body_path = resolved_out_dir / _artifact_name(mode, "segment_body_membership")
    trunk_path = resolved_out_dir / _artifact_name(mode, "trunk_membership")
    nodes_hash_path = resolved_out_dir / _artifact_name(mode, "nodes_hash")
    roads_hash_path = resolved_out_dir / _artifact_name(mode, "roads_hash")
    summary_path = resolved_out_dir / _artifact_name(mode, "summary")
    manifest_path = resolved_out_dir / _artifact_name(mode, "manifest")

    write_csv(
        validated_path,
        validated_rows,
        ["stage", "pair_id", "a_node_id", "b_node_id", "trunk_mode", "left_turn_excluded_mode", "segment_body_road_count", "residual_road_count"],
    )
    write_csv(segment_body_path, segment_body_rows, ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])
    write_csv(trunk_path, trunk_rows, ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])
    write_json(nodes_hash_path, _hash_payload(refreshed_nodes_path))
    write_json(roads_hash_path, _hash_payload(refreshed_roads_path))

    summary = {
        "skill_version": skill_version,
        "mode": mode,
        "freeze_label": freeze_label,
        "validated_pair_count": len(validated_rows),
        "segment_body_membership_count": len(segment_body_rows),
        "trunk_membership_count": len(trunk_rows),
        "refreshed_nodes_sha256": _hash_payload(refreshed_nodes_path)["sha256"],
        "refreshed_roads_sha256": _hash_payload(refreshed_roads_path)["sha256"],
    }
    manifest = {
        "skill_version": skill_version,
        "mode": mode,
        "freeze_label": freeze_label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_paths": {
            "step2_dir": str(step2_dir.resolve()),
            "step4_dir": str(step4_dir.resolve()),
            "step5_dir": str(step5_dir.resolve()),
            "refreshed_nodes_path": str(refreshed_nodes_path.resolve()),
            "refreshed_roads_path": str(refreshed_roads_path.resolve()),
        },
        "artifacts": {
            "validated_pairs": validated_path.name,
            "segment_body_membership": segment_body_path.name,
            "trunk_membership": trunk_path.name,
            "refreshed_nodes_hash": nodes_hash_path.name,
            "refreshed_roads_hash": roads_hash_path.name,
            "summary": summary_path.name,
        },
    }
    write_json(summary_path, summary)
    write_json(manifest_path, manifest)

    if mode == "baseline":
        rules_path = resolved_out_dir / BASELINE_RULES_NAME
        rules_path.write_text(
            "\n".join(
                [
                    "# T01 Skill v1.0.0 Freeze Compare Rules",
                    "",
                    "- 默认要求当前运行结果与 freeze baseline 完全一致。",
                    "- 对比范围至少包括 validated pair、segment_body membership、trunk membership、最终 refreshed nodes/roads hash。",
                    "- 任一集合或 hash 不一致，默认判定为 FAIL。",
                    "- 未经用户明确认可，不得更新本 freeze baseline。",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    return {
        "manifest_path": str(manifest_path.resolve()),
        "summary_path": str(summary_path.resolve()),
        "validated_pairs_path": str(validated_path.resolve()),
        "segment_body_membership_path": str(segment_body_path.resolve()),
        "trunk_membership_path": str(trunk_path.resolve()),
        "nodes_hash_path": str(nodes_hash_path.resolve()),
        "roads_hash_path": str(roads_hash_path.resolve()),
        "summary": summary,
    }


def compare_skill_v1_bundle(
    *,
    current_dir: Union[str, Path],
    freeze_dir: Union[str, Path],
    out_dir: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    current_dir = Path(current_dir)
    freeze_dir = Path(freeze_dir)
    resolved_out_dir = current_dir if out_dir is None else Path(out_dir)
    resolved_out_dir.mkdir(parents=True, exist_ok=True)

    current_validated = _read_csv_rows(current_dir / CURRENT_VALIDATED_NAME)
    current_segment = _read_csv_rows(current_dir / CURRENT_SEGMENT_BODY_NAME)
    current_trunk = _read_csv_rows(current_dir / CURRENT_TRUNK_NAME)
    baseline_validated = _read_csv_rows(freeze_dir / BASELINE_VALIDATED_NAME)
    baseline_segment = _read_csv_rows(freeze_dir / BASELINE_SEGMENT_BODY_NAME)
    baseline_trunk = _read_csv_rows(freeze_dir / BASELINE_TRUNK_NAME)

    current_nodes_hash = json.loads((current_dir / CURRENT_NODES_HASH_NAME).read_text(encoding="utf-8"))
    current_roads_hash = json.loads((current_dir / CURRENT_ROADS_HASH_NAME).read_text(encoding="utf-8"))
    baseline_nodes_hash = json.loads((freeze_dir / BASELINE_NODES_HASH_NAME).read_text(encoding="utf-8"))
    baseline_roads_hash = json.loads((freeze_dir / BASELINE_ROADS_HASH_NAME).read_text(encoding="utf-8"))

    comparisons = [
        _compare_row_sets(current_rows=current_validated, baseline_rows=baseline_validated, label="validated_pairs"),
        _compare_row_sets(current_rows=current_segment, baseline_rows=baseline_segment, label="segment_body_membership"),
        _compare_row_sets(current_rows=current_trunk, baseline_rows=baseline_trunk, label="trunk_membership"),
        _compare_hash_payloads(
            label="refreshed_nodes_hash",
            kind="nodes",
            current_dir=current_dir,
            freeze_dir=freeze_dir,
            current_hash=current_nodes_hash,
            baseline_hash=baseline_nodes_hash,
        ),
        _compare_hash_payloads(
            label="refreshed_roads_hash",
            kind="roads",
            current_dir=current_dir,
            freeze_dir=freeze_dir,
            current_hash=current_roads_hash,
            baseline_hash=baseline_roads_hash,
        ),
    ]

    has_fail = any(item["status"] == "FAIL" for item in comparisons)
    has_schema_migration = any(item["status"] == "SCHEMA_MIGRATION_DIFFERENCE" for item in comparisons)
    status = "FAIL" if has_fail else "PASS"
    report = {
        "status": status,
        "schema_migration_only": has_schema_migration and not has_fail,
        "current_dir": str(current_dir.resolve()),
        "freeze_dir": str(freeze_dir.resolve()),
        "comparisons": comparisons,
    }
    report_json_path = resolved_out_dir / "freeze_compare_report.json"
    report_md_path = resolved_out_dir / "freeze_compare_report.md"
    write_json(report_json_path, report)

    md_lines = [
        "# T01 Skill Freeze Compare Report",
        "",
        f"- status: `{status}`",
        f"- current_dir: `{current_dir.resolve()}`",
        f"- freeze_dir: `{freeze_dir.resolve()}`",
        "",
    ]
    for item in comparisons:
        md_lines.append(f"## {item['label']}")
        md_lines.append(f"- status: `{item['status']}`")
        if "current_count" in item:
            md_lines.append(f"- current_count: `{item['current_count']}`")
            md_lines.append(f"- baseline_count: `{item['baseline_count']}`")
            if item["status"] == "FAIL":
                md_lines.append(f"- only_in_current_sample: `{json.dumps(item['only_in_current_sample'], ensure_ascii=False)}`")
                md_lines.append(f"- only_in_baseline_sample: `{json.dumps(item['only_in_baseline_sample'], ensure_ascii=False)}`")
        else:
            md_lines.append(f"- current_sha256: `{item.get('current_sha256')}`")
            md_lines.append(f"- baseline_sha256: `{item.get('baseline_sha256')}`")
            if item.get("difference_type"):
                md_lines.append(f"- difference_type: `{item.get('difference_type')}`")
            if item.get("semantic_compare_available") is not None:
                md_lines.append(f"- semantic_compare_available: `{item.get('semantic_compare_available')}`")
        md_lines.append("")
    report_md_path.write_text("\n".join(md_lines), encoding="utf-8")
    report["report_json_path"] = str(report_json_path.resolve())
    report["report_md_path"] = str(report_md_path.resolve())
    return report


def _default_compare_out_root(*, run_id: Optional[str], cwd: Optional[Path] = None) -> tuple[Path, str]:
    resolved_run_id = run_id or f"t01_compare_freeze_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    repo_root = _find_repo_root(Path.cwd() if cwd is None else cwd)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_compare_freeze" / resolved_run_id, resolved_run_id


def run_compare_t01_freeze_cli(args: argparse.Namespace) -> int:
    if args.out_root is None:
        resolved_out_root, _ = _default_compare_out_root(run_id=args.run_id)
    else:
        resolved_out_root = Path(args.out_root)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    report = compare_skill_v1_bundle(current_dir=args.current_dir, freeze_dir=args.freeze_dir, out_dir=resolved_out_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
