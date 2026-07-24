from __future__ import annotations

import csv
import json
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p8_models import (
    DECISION_PARTIAL_GO,
    EXPECTED_DATASET_P0_DECISION,
    EXPECTED_P7_DECISION,
    SCHEME_A_P2_P3_P8_SCHEMA,
    SchemeAP2P3P8Config,
    choose_p8_decision,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


T03_PROMOTION_FIELDS = (
    "junction_type",
    "template_class",
    "association_class",
    "step7_state",
    "surface_candidate_present",
    "status_suggested",
    "relation_state",
    "required_rcsdnode_count",
    "required_rcsdroad_count",
    "support_rcsdnode_count",
    "support_rcsdroad_count",
    "excluded_rcsdnode_count",
    "excluded_rcsdroad_count",
)
T04_PROMOTION_FIELDS = (
    "junction_type",
    "scene_type",
    "final_state",
    "swsd_relation_type",
    "rcsd_profile",
    "has_c_unit",
    "surface_candidate_present",
    "status_suggested",
    "relation_state",
    "required_rcsd_node_count",
    "semantic_required_rcsd_node_count",
    "selected_rcsdnode_count",
    "selected_rcsdroad_count",
    "surface_scenario_type",
    "section_reference_source",
    "reference_point_present",
    "post_cleanup_allowed_growth_ok",
    "post_cleanup_forbidden_ok",
    "post_cleanup_terminal_cut_ok",
    "post_cleanup_lateral_limit_ok",
    "post_cleanup_must_cover_ok",
    "post_cleanup_recheck_performed",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_rcsdroad_localized",
    "fallback_overexpansion_detected",
    "divstrip_negative_mask_present",
    "forbidden_domain_kept",
    "single_connected_case_surface_ok",
    "barrier_separated_case_surface_ok",
)
PROMOTION_FIELDS = frozenset(T03_PROMOTION_FIELDS + T04_PROMOTION_FIELDS)
CARRIER_SIGNATURE_CONTEXT_ONLY_FIELDS = {
    "T04": frozenset({"junction_type", "scene_type"}),
}
LINEAGE_FIELDS = frozenset(
    {
        "target_id",
        "case_id",
        "mainnodeid",
        "anchor_id",
        "base_id_candidate",
        "patch_id",
        "sample_id",
        "group_id",
        "object_id",
        "fold",
    }
)
FREE_TEXT_FIELDS = frozenset(
    {
        "reason",
        "anchor_reason",
        "review_reason",
        "pre_gate_reason",
        "final_reason",
    }
)
CORE_ARTIFACTS = {
    "T03": (
        "nodes.gpkg",
        "summary.json",
        "virtual_intersection_polygons.gpkg",
        "t03_swsd_rcsd_relation_evidence.csv",
        "t03_swsd_rcsd_relation_evidence.json",
        "intersection_match_t03.geojson",
    ),
    "T04": (
        "nodes.gpkg",
        "divmerge_virtual_anchor_surface.gpkg",
        "divmerge_virtual_anchor_surface_audit.gpkg",
        "divmerge_virtual_anchor_surface_summary.csv",
        "t04_swsd_rcsd_relation_evidence.csv",
        "t04_swsd_rcsd_relation_evidence.json",
        "intersection_match_t04.geojson",
    ),
}
SOURCE_DOCS = (
    "modules/t03_virtual_junction_anchor/SPEC.md",
    "modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md",
    "modules/t03_virtual_junction_anchor/architecture/02-data-and-domain-model.md",
    "modules/t03_virtual_junction_anchor/architecture/04-evidence-and-audit.md",
    "modules/t04_divmerge_virtual_polygon/SPEC.md",
    "modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md",
    "modules/t04_divmerge_virtual_polygon/architecture/02-data-and-domain-model.md",
    "modules/t04_divmerge_virtual_polygon/architecture/04-evidence-and-audit.md",
)


def classify_field_role(name: str) -> str:
    normalized = name.strip().lower()
    if normalized in PROMOTION_FIELDS:
        return "PROMOTION_CANDIDATE"
    if normalized in LINEAGE_FIELDS or normalized.endswith("_id"):
        return "LINEAGE_ONLY"
    if normalized in FREE_TEXT_FIELDS or "reason" in normalized:
        return "PROHIBITED_FREE_TEXT"
    if normalized.endswith(("_x", "_y")) or "coordinate" in normalized:
        return "PROHIBITED_COORDINATE"
    if "path" in normalized or normalized.endswith("_png"):
        return "PROHIBITED_PATH"
    if "movement" in normalized:
        return "PROHIBITED_MOVEMENT"
    if any(
        token in normalized
        for token in ("truth", "label", "oracle", "review", "t05", "t06")
    ):
        return "PROHIBITED_DOWNSTREAM_OR_TRUTH"
    return "UNUSED"


def build_source_signature(fact: Mapping[str, Any]) -> str:
    source_module = str(fact.get("source_module") or "")
    context_only = CARRIER_SIGNATURE_CONTEXT_ONLY_FIELDS.get(
        source_module,
        frozenset(),
    )
    payload = {
        "source_module": source_module,
        "carrier_context_normalization": (
            "T04_DIVMERGE_DIRECTION_INVARIANT"
            if source_module == "T04"
            else "NONE"
        ),
        "values": {
            key: _canonical_scalar(fact.get(key))
            for key in sorted(PROMOTION_FIELDS)
            if key in fact and key not in context_only
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def join_segment_sources(
    junc_nodes: Sequence[str],
    source_by_target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for junction_id in sorted({str(value) for value in junc_nodes if value}):
        value = source_by_target.get(junction_id)
        if value is None:
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            rows.append(dict(candidate))
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("source_module") or ""),
            str(row.get("source_signature") or ""),
        ),
    )


def run_scheme_a_p2_p3_p8_audit(config: SchemeAP2P3P8Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)

    source = _load_sources(config)
    representations = _load_representations(
        source["p7_paths"]["representations"],
        config,
    )
    truths = _load_truths(
        source["p6_paths"]["object_attributions"],
        set(representations),
    )
    inventory = _load_inventory(
        source["dataset_paths"]["module_artifact_inventory"],
        config,
    )
    role_contract = _read_json(source["dataset_paths"]["module_role_contract"])
    eligible_cases = sorted(
        {str(row["case_key"]) for row in representations.values()}
    )
    source_facts, source_by_case, core_inventory, gis_audit = (
        _load_t03_t04_facts(inventory, eligible_cases, config)
    )
    t01_segments, t01_audit = _load_t01_segments(
        inventory,
        eligible_cases,
        config,
    )
    segment_rows = _build_segment_ledger(
        representations,
        source_by_case,
        t01_segments,
    )
    p7_neighborhood = _read_json(source["p7_paths"]["neighborhood_audit"])
    carrier_audit = _build_carrier_audit(
        segment_rows,
        truths,
        config,
    )
    clue_audit = _build_clue_audit(
        segment_rows,
        truths,
        p7_neighborhood,
        config,
    )
    field_contract = _build_field_contract(source_facts)
    source_audit = _build_source_audit(
        source,
        role_contract,
        eligible_cases,
        core_inventory,
        gis_audit,
        t01_audit,
        field_contract,
        segment_rows,
        config,
    )

    audit_gate = bool(source_audit["gate_pass"])
    carrier_gate = bool(carrier_audit["gate_pass"])
    clue_gate = bool(clue_audit["gate_pass"])
    deterministic_payload = {
        "source_lineage": source["lineage"],
        "source_fact_signature": _rows_signature(source_facts),
        "segment_ledger_signature": _rows_signature(segment_rows),
        "core_inventory_signature": _rows_signature(core_inventory),
        "field_contract": field_contract,
        "source_audit": source_audit,
        "carrier_audit": carrier_audit,
        "clue_audit": clue_audit,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)
    if reference_match is False:
        audit_gate = False

    peak_rss = _peak_rss_bytes()
    resource_metrics = {
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss,
        "peak_rss_gib": peak_rss / (1024**3),
        "gpu_vram_bytes": 0,
    }
    resource_gate = (
        resource_metrics["wall_seconds"] <= 10 * 60
        and peak_rss <= 8 * 1024**3
    )
    if not resource_gate:
        audit_gate = False
    decision = choose_p8_decision(audit_gate, carrier_gate, clue_gate)

    run_root.mkdir(parents=True)
    paths = {
        "core_artifact_inventory": run_root / "core_artifact_inventory.csv",
        "source_fact_ledger": run_root / "source_fact_ledger.jsonl",
        "segment_applicability": run_root / "segment_applicability.jsonl",
        "field_contract": run_root / "field_contract.json",
        "carrier_source_audit": run_root / "carrier_source_audit.json",
        "clue_source_audit": run_root / "clue_source_audit.json",
        "source_audit": run_root / "source_audit.json",
        "summary": run_root / "scheme_a_p2_p3_p8_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_csv(paths["core_artifact_inventory"], core_inventory)
    _write_jsonl(paths["source_fact_ledger"], source_facts)
    _write_jsonl(paths["segment_applicability"], segment_rows)
    write_json(paths["field_contract"], field_contract)
    write_json(paths["carrier_source_audit"], carrier_audit)
    write_json(paths["clue_source_audit"], clue_audit)
    write_json(paths["source_audit"], source_audit)

    summary = {
        "schema_version": SCHEME_A_P2_P3_P8_SCHEMA,
        "decision": decision,
        "input_p7_decision": EXPECTED_P7_DECISION,
        "dataset_p0_decision": EXPECTED_DATASET_P0_DECISION,
        "audit_gate_pass": audit_gate,
        "carrier_source_gate_pass": carrier_gate,
        "clue_source_gate_pass": clue_gate,
        "resource_gate_pass": resource_gate,
        "reference_run_match": reference_match,
        "determinism_signature": signature,
        "eligible_count": len(segment_rows),
        "eligible_case_count": len(eligible_cases),
        "applicable_group_count": sum(
            bool(row["source_applicable"]) for row in segment_rows
        ),
        "multi_source_group_count": sum(
            int(row["source_count"]) > 1 for row in segment_rows
        ),
        "source_fact_count": len(source_facts),
        "stable_carrier_audit": carrier_audit,
        "stable_clue_coverage": {
            key: clue_audit[key]
            for key in (
                "stable_group_count",
                "applicable_group_count",
                "missing_group_count",
                "semantic_conflict_count",
            )
        },
        "current_t03_t04_model_input": False,
        "current_t03_t04_label_only": True,
        "promotion_applied": False,
        "model_training_count": 0,
        "calibrator_fit_count": 0,
        "threshold_tuning_count": 0,
        "movement_feature_count": 0,
        "t05_t06_input_count": 0,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "path_feature_count": 0,
        "free_text_feature_count": 0,
        "geometry_read_count": gis_audit["geometry_read_count"],
        "geometry_write_count": 0,
        "coordinate_transform_count": 0,
        "spatial_join_count": 0,
        "cross_case_join_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "resource": resource_metrics,
        "source_lineage": source["lineage"],
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(
        _render_report(summary),
        encoding="utf-8",
    )
    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p8_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P8_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "t03_t04_inference_source_contract_audit_completed",
            "decision": decision,
            "input_p7_decision": EXPECTED_P7_DECISION,
            "dataset_p0_decision": EXPECTED_DATASET_P0_DECISION,
            "determinism_signature": signature,
            "reference_run_match": reference_match,
            "lineage": source["lineage"],
            "outputs": outputs,
            "promotion_applied": False,
            "model_training_count": 0,
            "calibrator_fit_count": 0,
            "threshold_tuning_count": 0,
            "movement_feature_count": 0,
            "t05_t06_input_count": 0,
            "geometry_read_count": gis_audit["geometry_read_count"],
            "geometry_write_count": 0,
            "coordinate_transform_count": 0,
            "spatial_join_count": 0,
            "skeleton_mutation_count": 0,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p8-artifacts-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def _load_sources(config: SchemeAP2P3P8Config) -> dict[str, Any]:
    roots = {
        "p7": normalize_runtime_path(config.p7_run_root).resolve(strict=True),
        "p6": normalize_runtime_path(config.p6_run_root).resolve(strict=True),
        "dataset": normalize_runtime_path(config.dataset_p0_root).resolve(
            strict=True
        ),
        "repository": normalize_runtime_path(config.repository_root).resolve(
            strict=True
        ),
    }
    manifest_paths = {
        "p7": roots["p7"] / "scheme_a_p2_p3_p7_manifest.json",
        "p6": roots["p6"] / "scheme_a_p2_p3_p6_manifest.json",
        "dataset": roots["dataset"] / "dataset_p0_manifest.json",
    }
    manifests = {key: _read_json(path) for key, path in manifest_paths.items()}
    paths = {
        key: _verified_outputs(manifest, config.strict_hashes)
        for key, manifest in manifests.items()
    }
    docs = []
    for relative in SOURCE_DOCS:
        path = roots["repository"] / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        docs.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "t05_handoff_declared": "T05" in path.read_text(
                    encoding="utf-8"
                ),
            }
        )
    return {
        "roots": roots,
        "manifests": manifests,
        "p7_paths": paths["p7"],
        "p6_paths": paths["p6"],
        "dataset_paths": paths["dataset"],
        "source_docs": docs,
        "lineage": {
            **{
                f"{key}_manifest_sha256": sha256_file(path)
                for key, path in manifest_paths.items()
            },
            "source_docs_signature": _rows_signature(docs),
        },
    }


def _load_representations(
    path: Path,
    config: SchemeAP2P3P8Config,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        stable = {
            "group_id": str(row["group_id"]),
            "case_key": str(row["case_key"]),
            "object_id": str(row["object_id"]),
            "fold": int(row["fold"]),
        }
        if stable["group_id"] in result:
            raise ValueError(f"duplicate P7 group: {stable['group_id']}")
        result[stable["group_id"]] = stable
    if len(result) != config.expected_eligible_count:
        raise ValueError("P7 eligible count differs")
    if len({row["case_key"] for row in result.values()}) != (
        config.expected_case_count
    ):
        raise ValueError("P7 eligible Case count differs")
    return result


def _load_truths(
    path: Path,
    eligible: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        if int(row["seed"]) != 311:
            continue
        group_id = str(row["group_id"])
        if group_id not in eligible:
            continue
        result[group_id] = {
            "truth_target": str(row["truth_target"]),
            "clue_target": bool(row["clue_target"]),
            "review_target": bool(row["review_target"]),
        }
    if set(result) != eligible:
        raise ValueError("P6 seed 311 truth scope differs")
    return result


def _load_inventory(
    path: Path,
    config: SchemeAP2P3P8Config,
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_csv(path):
        module = str(row["module"])
        if module not in {"T01", "T03", "T04"}:
            continue
        case_key = f"{row['family']}:{row['business_id']}"
        key = (case_key, module)
        if key in result:
            raise ValueError(f"duplicate inventory row: {key}")
        path_value = normalize_runtime_path(Path(row["path"])).resolve(
            strict=True
        )
        if str(row["hash_status"]) != "ok":
            raise ValueError(f"inventory hash status not ok: {key}")
        if config.strict_hashes and sha256_file(path_value) != row["sha256"]:
            raise ValueError(f"inventory hash differs: {key}")
        result[key] = {**row, "resolved_path": path_value}
    return result


def _load_t03_t04_facts(
    inventory: Mapping[tuple[str, str], Mapping[str, Any]],
    eligible_cases: Sequence[str],
    config: SchemeAP2P3P8Config,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, list[dict[str, Any]]]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    facts: list[dict[str, Any]] = []
    by_case: dict[str, dict[str, list[dict[str, Any]]]] = {}
    core_rows: list[dict[str, Any]] = []
    crs_counts: Counter[str] = Counter()
    geometry_read_count = 0
    for case_key in eligible_cases:
        case_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for module in ("T03", "T04"):
            entry = inventory.get((case_key, module))
            if entry is None:
                raise ValueError(f"missing {module} inventory: {case_key}")
            root = Path(entry["resolved_path"]).parent
            for name in CORE_ARTIFACTS[module]:
                path = root / name
                if not path.is_file():
                    raise FileNotFoundError(path)
                core_rows.append(
                    {
                        "case_key": case_key,
                        "source_module": module,
                        "artifact_name": name,
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
                if path.suffix == ".gpkg":
                    for layer in fiona.listlayers(path):
                        with fiona.open(path, layer=layer) as dataset:
                            crs_counts[str(dataset.crs)] += 1
                            geometry_read_count += 1
            if module == "T03":
                rows = _read_csv(root / "t03_swsd_rcsd_relation_evidence.csv")
                module_facts = [_t03_fact(row, case_key) for row in rows]
            else:
                summaries = {
                    str(row["mainnodeid"]): row
                    for row in _read_csv(
                        root / "divmerge_virtual_anchor_surface_summary.csv"
                    )
                }
                rows = _read_csv(root / "t04_swsd_rcsd_relation_evidence.csv")
                module_facts = [
                    _t04_fact(
                        row,
                        summaries.get(str(row["target_id"]), {}),
                        case_key,
                    )
                    for row in rows
                ]
            seen: set[str] = set()
            for fact in module_facts:
                target_id = str(fact["target_id"])
                if target_id in seen:
                    raise ValueError(
                        f"duplicate {module} target: {case_key}/{target_id}"
                    )
                seen.add(target_id)
                fact["source_signature"] = build_source_signature(fact)
                facts.append(fact)
                case_sources[target_id].append(fact)
        by_case[case_key] = dict(case_sources)
    facts.sort(
        key=lambda row: (
            row["case_key"],
            row["source_module"],
            row["target_id"],
        )
    )
    core_rows.sort(
        key=lambda row: (
            row["case_key"],
            row["source_module"],
            row["artifact_name"],
        )
    )
    return (
        facts,
        by_case,
        core_rows,
        {
            "geometry_read_count": geometry_read_count,
            "crs_counts": dict(sorted(crs_counts.items())),
            "expected_source_crs": "EPSG:3857",
            "all_source_gpkg_epsg3857": set(crs_counts) == {"EPSG:3857"},
            "geometry_write_count": 0,
            "coordinate_transform_count": 0,
        },
    )


def _t03_fact(row: Mapping[str, Any], case_key: str) -> dict[str, Any]:
    values = {
        "source_module": "T03",
        "case_key": case_key,
        "target_id": str(row["target_id"]),
        "junction_type": row.get("junction_type"),
        "template_class": row.get("template_class"),
        "association_class": row.get("association_class"),
        "step7_state": row.get("step7_state"),
        "surface_candidate_present": _integer(row.get("surface_candidate_present")),
        "status_suggested": _integer(row.get("status_suggested")),
        "relation_state": row.get("relation_state"),
        "required_rcsdnode_count": _pipe_count(
            row.get("required_rcsdnode_ids")
        ),
        "required_rcsdroad_count": _pipe_count(
            row.get("required_rcsdroad_ids")
        ),
        "support_rcsdnode_count": _pipe_count(
            row.get("support_rcsdnode_ids")
        ),
        "support_rcsdroad_count": _pipe_count(
            row.get("support_rcsdroad_ids")
        ),
        "excluded_rcsdnode_count": _pipe_count(
            row.get("excluded_rcsdnode_ids")
        ),
        "excluded_rcsdroad_count": _pipe_count(
            row.get("excluded_rcsdroad_ids")
        ),
    }
    return values


def _t04_fact(
    row: Mapping[str, Any],
    summary: Mapping[str, Any],
    case_key: str,
) -> dict[str, Any]:
    result = {
        "source_module": "T04",
        "case_key": case_key,
        "target_id": str(row["target_id"]),
        "junction_type": row.get("junction_type"),
        "scene_type": row.get("scene_type"),
        "final_state": row.get("final_state"),
        "swsd_relation_type": row.get("swsd_relation_type"),
        "rcsd_profile": row.get("rcsd_profile"),
        "has_c_unit": _integer(row.get("has_c_unit")),
        "surface_candidate_present": _integer(row.get("surface_candidate_present")),
        "status_suggested": _integer(row.get("status_suggested")),
        "relation_state": row.get("relation_state"),
        "required_rcsd_node_count": _pipe_count(
            row.get("required_rcsd_node_ids")
        ),
        "semantic_required_rcsd_node_count": _pipe_count(
            row.get("semantic_required_rcsd_node_ids")
        ),
        "selected_rcsdnode_count": _pipe_count(
            row.get("selected_rcsdnode_ids")
        ),
        "selected_rcsdroad_count": _pipe_count(
            row.get("selected_rcsdroad_ids")
        ),
    }
    summary_fields = set(T04_PROMOTION_FIELDS) - set(result)
    for name in sorted(summary_fields):
        value = summary.get(name)
        if name in {
            "reference_point_present",
            "post_cleanup_allowed_growth_ok",
            "post_cleanup_forbidden_ok",
            "post_cleanup_terminal_cut_ok",
            "post_cleanup_lateral_limit_ok",
            "post_cleanup_must_cover_ok",
            "post_cleanup_recheck_performed",
            "no_surface_reference_guard",
            "final_polygon_suppressed_by_no_surface_reference",
            "fallback_rcsdroad_localized",
            "fallback_overexpansion_detected",
            "divstrip_negative_mask_present",
            "forbidden_domain_kept",
            "single_connected_case_surface_ok",
            "barrier_separated_case_surface_ok",
        }:
            value = _boolean(value)
        result[name] = value
    return result


def _load_t01_segments(
    inventory: Mapping[tuple[str, str], Mapping[str, Any]],
    eligible_cases: Sequence[str],
    config: SchemeAP2P3P8Config,
) -> tuple[dict[tuple[str, str], tuple[str, ...]], dict[str, Any]]:
    segments: dict[tuple[str, str], tuple[str, ...]] = {}
    crs_counts: Counter[str] = Counter()
    for case_key in eligible_cases:
        entry = inventory.get((case_key, "T01"))
        if entry is None:
            raise ValueError(f"missing T01 inventory: {case_key}")
        path = Path(entry["resolved_path"])
        with fiona.open(path) as dataset:
            crs_counts[str(dataset.crs)] += 1
            for feature in dataset:
                props = dict(feature["properties"])
                object_id = str(props["id"])
                key = (case_key, object_id)
                if key in segments:
                    raise ValueError(f"duplicate T01 Segment: {key}")
                segments[key] = _split_ids(props.get("junc_nodes"))
    return (
        segments,
        {
            "segment_gpkg_read_count": len(eligible_cases),
            "crs_counts": dict(sorted(crs_counts.items())),
            "all_segment_gpkg_epsg3857": set(crs_counts) == {"EPSG:3857"},
            "join_field": "junc_nodes",
            "spatial_join_count": 0,
            "cross_case_join_count": 0,
        },
    )


def _build_segment_ledger(
    representations: Mapping[str, Mapping[str, Any]],
    source_by_case: Mapping[str, Mapping[str, Any]],
    segments: Mapping[tuple[str, str], tuple[str, ...]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group_id in sorted(representations):
        row = representations[group_id]
        case_key = str(row["case_key"])
        object_id = str(row["object_id"])
        key = (case_key, object_id)
        if key not in segments:
            raise ValueError(f"P7 Segment missing from T01: {key}")
        junction_ids = segments[key]
        matches = join_segment_sources(
            junction_ids,
            source_by_case.get(case_key, {}),
        )
        source_facts = [
            {
                key: value
                for key, value in match.items()
                if key
                not in {
                    "case_key",
                    "target_id",
                }
            }
            for match in matches
        ]
        result.append(
            {
                "schema_version": SCHEME_A_P2_P3_P8_SCHEMA,
                "group_id": group_id,
                "case_key": case_key,
                "object_id": object_id,
                "fold": int(row["fold"]),
                "junc_nodes": list(junction_ids),
                "junction_count": len(junction_ids),
                "source_applicable": bool(matches),
                "source_count": len(matches),
                "source_modules": sorted(
                    {str(match["source_module"]) for match in matches}
                ),
                "source_signatures": [
                    str(match["source_signature"]) for match in matches
                ],
                "source_facts": source_facts,
                "join_method": "CASE_LOCAL_T01_JUNC_NODES_EXACT_ID",
                "absence_semantics": (
                    "NOT_APPLICABLE" if not matches else "APPLICABLE"
                ),
            }
        )
    return result


def _build_carrier_audit(
    segment_rows: Sequence[Mapping[str, Any]],
    truths: Mapping[str, Mapping[str, Any]],
    config: SchemeAP2P3P8Config,
) -> dict[str, Any]:
    by_group = {str(row["group_id"]): row for row in segment_rows}
    query = by_group.get(config.stable_carrier_wrong_group)
    if query is None:
        raise ValueError("stable carrier wrong group missing")
    query_signatures = set(query["source_signatures"])
    peers = []
    for row in segment_rows:
        group_id = str(row["group_id"])
        if int(row["fold"]) == int(query["fold"]):
            continue
        shared = sorted(query_signatures & set(row["source_signatures"]))
        if not shared:
            continue
        truth = truths[group_id]
        peers.append(
            {
                "group_id": group_id,
                "case_key": row["case_key"],
                "object_id": row["object_id"],
                "fold": row["fold"],
                "shared_source_signatures": shared,
                "truth_target": truth["truth_target"],
                "clue_target": truth["clue_target"],
            }
        )
    peers.sort(key=lambda row: str(row["group_id"]))
    truth_counts = Counter(str(row["truth_target"]) for row in peers)
    clue_true_count = sum(bool(row["clue_target"]) for row in peers)
    heldout_case_leakage_count = sum(
        row["case_key"] == query["case_key"] for row in peers
    )
    gate = (
        bool(query["source_applicable"])
        and len(peers) >= config.expected_carrier_peer_count
        and truth_counts.get("KEEP_SWSD", 0) == len(peers)
        and truth_counts.get("USE_RCSD", 0) == 0
        and clue_true_count >= 1
        and heldout_case_leakage_count == 0
    )
    return {
        "gate_pass": gate,
        "query_group_id": config.stable_carrier_wrong_group,
        "query_case_key": query["case_key"],
        "query_object_id": query["object_id"],
        "query_fold": query["fold"],
        "query_source_applicable": query["source_applicable"],
        "query_source_signatures": sorted(query_signatures),
        "train_only_peer_count": len(peers),
        "expected_min_peer_count": config.expected_carrier_peer_count,
        "peer_truth_counts": dict(sorted(truth_counts.items())),
        "peer_clue_true_count": clue_true_count,
        "heldout_case_leakage_count": heldout_case_leakage_count,
        "peers": peers,
        "truth_or_fold_in_source_signature": False,
    }


def _build_clue_audit(
    segment_rows: Sequence[Mapping[str, Any]],
    truths: Mapping[str, Mapping[str, Any]],
    p7_neighborhood: Mapping[str, Any],
    config: SchemeAP2P3P8Config,
) -> dict[str, Any]:
    by_group = {str(row["group_id"]): row for row in segment_rows}
    stable_source = p7_neighborhood.get("stable_group_neighbor_audits") or []
    stable_ids = sorted({str(row["group_id"]) for row in stable_source})
    if len(stable_ids) != config.expected_stable_group_count:
        raise ValueError("P7 stable clue group count differs")
    rows = []
    for group_id in stable_ids:
        segment = by_group[group_id]
        truth = truths[group_id]
        rows.append(
            {
                "group_id": group_id,
                "case_key": segment["case_key"],
                "object_id": segment["object_id"],
                "truth_target": truth["truth_target"],
                "clue_target": truth["clue_target"],
                "source_applicable": segment["source_applicable"],
                "source_modules": segment["source_modules"],
                "source_signatures": segment["source_signatures"],
                "semantic_conflict": False,
                "absence_semantics": segment["absence_semantics"],
            }
        )
    applicable = sum(bool(row["source_applicable"]) for row in rows)
    conflicts = sum(bool(row["semantic_conflict"]) for row in rows)
    gate = applicable == len(rows) and conflicts == 0
    return {
        "gate_pass": gate,
        "stable_group_count": len(rows),
        "applicable_group_count": applicable,
        "missing_group_count": len(rows) - applicable,
        "semantic_conflict_count": conflicts,
        "absence_is_negative_feature": False,
        "groups": rows,
    }


def _build_field_contract(
    source_facts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    read_fields = sorted(
        {key for row in source_facts for key in row if key != "source_signature"}
    )
    roles = {key: classify_field_role(key) for key in read_fields}
    promotion_fields = sorted(
        key for key, role in roles.items() if role == "PROMOTION_CANDIDATE"
    )
    return {
        "schema_version": "p05-scheme-a-p2-p3-p8-field-contract-v1",
        "current_t03_t04_model_input": False,
        "current_t03_t04_label_only": True,
        "promotion_applied": False,
        "promotion_candidate_fields": promotion_fields,
        "promotion_candidate_field_count": len(promotion_fields),
        "field_roles": roles,
        "source_signature_fields": [
            "source_module",
            *sorted(
                set(promotion_fields)
                - set().union(*CARRIER_SIGNATURE_CONTEXT_ONLY_FIELDS.values())
            ),
        ],
        "carrier_signature_context_only_fields": {
            module: sorted(fields)
            for module, fields in CARRIER_SIGNATURE_CONTEXT_ONLY_FIELDS.items()
        },
        "carrier_signature_normalization": (
            "T04 merge/diverge remain promotion-candidate context fields, "
            "but do not split the carrier safety state identity"
        ),
        "lineage_only_fields": sorted(
            key for key, role in roles.items() if role == "LINEAGE_ONLY"
        ),
        "explicitly_prohibited_patterns": [
            "identifier",
            "absolute_coordinate",
            "path",
            "free_text_reason",
            "review_only",
            "T05_or_T06_terminal_state",
            "truth_or_label_or_oracle",
            "Movement",
        ],
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "path_feature_count": 0,
        "free_text_feature_count": 0,
        "review_feature_count": 0,
        "t05_t06_feature_count": 0,
        "movement_feature_count": 0,
    }


def _build_source_audit(
    source: Mapping[str, Any],
    role_contract: Sequence[Mapping[str, Any]],
    eligible_cases: Sequence[str],
    core_inventory: Sequence[Mapping[str, Any]],
    gis_audit: Mapping[str, Any],
    t01_audit: Mapping[str, Any],
    field_contract: Mapping[str, Any],
    segment_rows: Sequence[Mapping[str, Any]],
    config: SchemeAP2P3P8Config,
) -> dict[str, Any]:
    role_by_module = {str(row["module"]): row for row in role_contract}
    role_gate = all(
        module in role_by_module
        and role_by_module[module].get("model_input") is False
        and role_by_module[module].get("label_only") is True
        for module in ("T03", "T04")
    )
    source_doc_gate = all(
        bool(row["t05_handoff_declared"]) for row in source["source_docs"]
    )
    manifest_gate = (
        source["manifests"]["p7"].get("decision") == EXPECTED_P7_DECISION
        and source["manifests"]["dataset"].get("decision")
        == EXPECTED_DATASET_P0_DECISION
    )
    expected_core = len(eligible_cases) * sum(
        len(names) for names in CORE_ARTIFACTS.values()
    )
    fields_gate = all(
        int(field_contract[key]) == 0
        for key in (
            "truth_feature_count",
            "identifier_feature_count",
            "absolute_coordinate_feature_count",
            "path_feature_count",
            "free_text_feature_count",
            "review_feature_count",
            "t05_t06_feature_count",
            "movement_feature_count",
        )
    )
    ledger_gate = (
        len(segment_rows) == config.expected_eligible_count
        and all(row["join_method"] == "CASE_LOCAL_T01_JUNC_NODES_EXACT_ID"
                for row in segment_rows)
    )
    gates = {
        "manifest_decisions": manifest_gate,
        "current_roles_preserved": role_gate,
        "source_docs_declare_t05_handoff": source_doc_gate,
        "eligible_case_count": len(eligible_cases) == config.expected_case_count,
        "core_artifact_count": len(core_inventory) == expected_core,
        "source_gpkg_crs": bool(gis_audit["all_source_gpkg_epsg3857"]),
        "t01_segment_crs": bool(t01_audit["all_segment_gpkg_epsg3857"]),
        "field_contract": fields_gate,
        "segment_ledger": ledger_gate,
        "no_spatial_or_cross_case_join": (
            int(t01_audit["spatial_join_count"]) == 0
            and int(t01_audit["cross_case_join_count"]) == 0
        ),
    }
    return {
        "gate_pass": all(gates.values()),
        "gates": gates,
        "source_docs": source["source_docs"],
        "current_roles": {
            module: role_by_module.get(module) for module in ("T03", "T04")
        },
        "eligible_case_count": len(eligible_cases),
        "core_artifact_count": len(core_inventory),
        "expected_core_artifact_count": expected_core,
        "applicable_group_count": sum(
            bool(row["source_applicable"]) for row in segment_rows
        ),
        "no_source_group_count": sum(
            not bool(row["source_applicable"]) for row in segment_rows
        ),
        "multi_source_group_count": sum(
            int(row["source_count"]) > 1 for row in segment_rows
        ),
        "gis": dict(gis_audit),
        "t01_join": dict(t01_audit),
        "t03_t04_input_count_from_t05_t06": 0,
        "promotion_applied": False,
        "silent_merge_count": 0,
    }


def _render_report(summary: Mapping[str, Any]) -> str:
    carrier = summary["stable_carrier_audit"]
    clue = summary["stable_clue_coverage"]
    return "\n".join(
        (
            "# P05 Scheme A P2-P3-P8 validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- audit gate: `{summary['audit_gate_pass']}`",
            f"- carrier source gate: `{summary['carrier_source_gate_pass']}`",
            f"- clue source gate: `{summary['clue_source_gate_pass']}`",
            f"- eligible: `{summary['eligible_count']}` / "
            f"`{summary['eligible_case_count']}` Cases",
            f"- applicable groups: `{summary['applicable_group_count']}`",
            f"- multi-source groups: `{summary['multi_source_group_count']}`",
            f"- carrier train-only exact peers: "
            f"`{carrier['train_only_peer_count']}`",
            f"- carrier peer truth: `{carrier['peer_truth_counts']}`",
            f"- stable clue source coverage: "
            f"`{clue['applicable_group_count']}/{clue['stable_group_count']}`",
            f"- deterministic signature: `{summary['determinism_signature']}`",
            f"- reference match: `{summary['reference_run_match']}`",
            "- training/calibration/threshold tuning: `0/0/0`",
            "- promotion applied: `false`",
            "- geometry write/transform/spatial join/silent fix: `0/0/0/false`",
            "",
        )
    )


def _verified_outputs(
    manifest: Mapping[str, Any],
    strict_hashes: bool,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for key, value in dict(manifest.get("outputs") or {}).items():
        path = normalize_runtime_path(Path(value["path"])).resolve(strict=True)
        if strict_hashes and sha256_file(path) != value["sha256"]:
            raise ValueError(f"manifest output hash differs: {key}")
        result[str(key)] = path
    return result


def _reference_match(reference_root: Path | None, signature: str) -> bool | None:
    if reference_root is None:
        return None
    root = normalize_runtime_path(reference_root).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p8_manifest.json")
    return str(manifest.get("determinism_signature") or "") == signature


def _canonical_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _pipe_count(value: Any) -> int:
    return len(_split_ids(value))


def _split_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text:
        return ()
    normalized = text.replace(",", "|")
    return tuple(sorted({part.strip() for part in normalized.split("|")
                         if part.strip()}))


def _integer(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value)))


def _boolean(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean: {value}")


def _rows_signature(rows: Iterable[Mapping[str, Any]]) -> str:
    return canonical_sha256(list(rows))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            stream.write("\n")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError("CSV output requires rows")
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


__all__ = [
    "build_source_signature",
    "classify_field_role",
    "join_segment_sources",
    "run_scheme_a_p2_p3_p8_audit",
]
