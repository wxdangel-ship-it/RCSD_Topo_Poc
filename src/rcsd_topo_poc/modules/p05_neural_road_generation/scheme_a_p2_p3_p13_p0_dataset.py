from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from shapely.geometry import Point

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _case_input_records,
    _parse_access,
    _read_crs,
    _read_csv,
    _read_json,
    _read_jsonl,
    _read_nodes,
    _read_roads,
    _resolve_case_paths,
    _row_key,
    _segment_geometry,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_audit import (
    DECISION_GO as R1_DECISION_GO,
    _candidate_config,
    _candidate_key,
    _evidence_key,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_candidates import (
    build_truth_free_case_candidates,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_models import (
    P12RR1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_models import (
    P13P0Config,
    SCHEMA_VERSION,
)


FEATURE_NAMES = (
    "source_local_5m",
    "source_endpoint_junction",
    "endpoint_evidence_complete",
    "orientation_forward",
    "orientation_reverse",
    "orientation_same_owner",
    "orientation_ambiguous",
    "orientation_unresolved",
    "orientation_missing",
    "access_valid",
    "same_owner_segment",
    "candidate_count_log",
    "control_candidate_count_log",
    "endpoint_candidate_count_log",
    "bundle_count_log",
    "bundle_size_log",
    "bundle_control_count_log",
    "bundle_edge_count_log",
    "bundle_sequential_edge_count_log",
    "bundle_parallel_edge_count_log",
    "bundle_source_boundary_count_log",
    "bundle_target_boundary_count_log",
    "source_incident_count_log",
    "target_incident_count_log",
    "road_length_log_m",
    "road_endpoint_distance_log_m",
    "road_straightness",
    "road_to_swsd_distance_log_m",
    "road_to_swsd_hausdorff_log_m",
    "start_to_source_access_log_m",
    "end_to_source_access_log_m",
    "start_to_target_access_log_m",
    "end_to_target_access_log_m",
    "forward_access_cost_log_m",
    "reverse_access_cost_log_m",
    "best_owner_distance_log_m",
    "forward_source_distance_log_m",
    "forward_target_distance_log_m",
    "reverse_source_distance_log_m",
    "reverse_target_distance_log_m",
    "owner_distance_missing",
    "source_incident_missing",
    "target_incident_missing",
    "road_is_bundle_source_boundary",
    "road_is_bundle_target_boundary",
    "road_candidate_indegree_log",
    "road_candidate_outdegree_log",
    "rank_swsd_distance",
    "rank_forward_access_cost",
    "rank_road_length",
)


def build_truth_free_feature_dataset(
    config: P13P0Config,
) -> dict[str, Any]:
    summary = _read_json(config.r1_run_root / "r1_summary.json")
    manifest = _read_json(config.r1_run_root / "r1_manifest.json")
    if str(summary["decision"]) != R1_DECISION_GO:
        raise ValueError("P13-P0 requires an R1 candidate GO run")
    if (
        str(summary["candidate_frozen_signature"])
        != config.expected_r1_candidate_signature
    ):
        raise ValueError("R1 candidate signature differs from P13 contract")
    _verify_artifact_manifest(config.r1_run_root)

    r1_cfg = P12RR1Config(**manifest["config"])
    r1_candidates = _read_jsonl(
        config.r1_run_root / "advance_right_endpoint_candidates.jsonl"
    )
    r1_evidence = _read_jsonl(
        config.r1_run_root / "endpoint_evidence_audit.jsonl"
    )
    candidate_clean = sorted(
        [
            {
                key: value
                for key, value in row.items()
                if key not in {"candidate_frozen_signature", "fold"}
            }
            for row in r1_candidates
        ],
        key=_candidate_key,
    )
    evidence_clean = sorted(
        [
            {key: value for key, value in row.items() if key != "fold"}
            for row in r1_evidence
        ],
        key=_evidence_key,
    )

    case_inventory_path = (
        config.scheme_a_baseline_root / "case_inventory.csv"
    )
    case_inventory = _read_csv(case_inventory_path)
    case_rows = [
        row
        for row in case_inventory
        if int(row.get("advance_right_count") or 0) > 0
    ]
    inference_inputs = [
        _input_record(
            config.r1_run_root / "r1_summary.json",
            "R1_SUMMARY_INFERENCE_CONTRACT",
        ),
        _input_record(
            config.r1_run_root / "r1_manifest.json",
            "R1_MANIFEST_INFERENCE_CONTRACT",
        ),
        _input_record(
            config.r1_run_root / "advance_right_endpoint_candidates.jsonl",
            "R1_TRUTH_FREE_CANDIDATES",
        ),
        _input_record(
            config.r1_run_root / "endpoint_evidence_audit.jsonl",
            "R1_TRUTH_FREE_ENDPOINT_EVIDENCE",
        ),
        _input_record(
            case_inventory_path,
            "SCHEME_A_CASE_INVENTORY",
        ),
    ]

    rebuilt_candidates: list[dict[str, Any]] = []
    rebuilt_evidence: list[dict[str, Any]] = []
    rebuilt_objects: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    crs_by_case: dict[str, dict[str, Any]] = {}
    for case_row in sorted(case_rows, key=lambda row: str(row["case_key"])):
        paths, skeleton = _resolve_case_paths(
            baseline_root=config.scheme_a_baseline_root,
            case_row=case_row,
            poc_data_root=config.poc_data_root,
        )
        t01_roads = _read_roads(paths.t01_roads)
        t01_nodes = _read_nodes(paths.t01_nodes)
        raw_roads = _read_roads(paths.raw_rcsd_roads)
        rebuilt = build_truth_free_case_candidates(
            case_key=paths.case_key,
            skeleton=skeleton,
            t01_roads=t01_roads,
            raw_rcsd_roads=raw_roads,
            config=r1_cfg,
        )
        rebuilt_candidates.extend(rebuilt["candidates"])
        rebuilt_evidence.extend(rebuilt["evidence"])
        rebuilt_objects.extend(rebuilt["objects"])
        case_features, case_objects = _case_feature_rows(
            case_key=paths.case_key,
            skeleton=skeleton,
            t01_roads=t01_roads,
            t01_nodes=t01_nodes,
            raw_roads=raw_roads,
            candidates=rebuilt["candidates"],
            evidence_rows=rebuilt["evidence"],
            object_rows=rebuilt["objects"],
        )
        feature_rows.extend(case_features)
        object_rows.extend(case_objects)
        crs_values = (
            _read_crs(paths.t01_roads),
            _read_crs(paths.t01_nodes),
            _read_crs(paths.raw_rcsd_roads),
            _read_crs(paths.raw_rcsd_nodes),
        )
        crs_by_case[paths.case_key] = {
            "consistent": len(set(crs_values)) == 1,
            "crs": crs_values[0],
            "metric": _metric_projected(crs_values[0]),
        }
        for record in _case_input_records(paths):
            role = str(record["role"])
            if (
                any(
                    token in role
                    for token in (
                        "frozen_skeleton.json",
                        "roads.gpkg",
                        "nodes.gpkg",
                        "rcsdroad_slice.gpkg",
                        "rcsdnode_slice.gpkg",
                    )
                )
                and "t06_" not in role
            ):
                inference_inputs.append(record)

    rebuilt_candidates.sort(key=_candidate_key)
    rebuilt_evidence.sort(key=_evidence_key)
    rebuilt_objects.sort(key=_row_key)
    if rebuilt_candidates != candidate_clean:
        raise ValueError("P13 candidate replay differs from formal R1")
    if rebuilt_evidence != evidence_clean:
        raise ValueError("P13 endpoint evidence replay differs from formal R1")
    candidate_signature = canonical_sha256(
        {
            "candidates": rebuilt_candidates,
            "config": _candidate_config(r1_cfg),
            "evidence": rebuilt_evidence,
            "objects": rebuilt_objects,
        }
    )
    if candidate_signature != config.expected_r1_candidate_signature:
        raise ValueError("P13 replayed candidate signature differs")

    feature_rows.sort(key=_candidate_key)
    object_rows.sort(key=_row_key)
    feature_signature = canonical_sha256(
        {
            "candidate_signature": candidate_signature,
            "feature_names": FEATURE_NAMES,
            "feature_rows": feature_rows,
            "object_rows": object_rows,
            "schema_version": SCHEMA_VERSION,
        }
    )
    return {
        "candidate_signature": candidate_signature,
        "crs_by_case": crs_by_case,
        "feature_names": list(FEATURE_NAMES),
        "feature_rows": feature_rows,
        "feature_signature": feature_signature,
        "inference_inputs": _deduplicate_inputs(inference_inputs),
        "object_rows": object_rows,
    }


def attach_label_only_targets(
    feature_dataset: Mapping[str, Any],
    config: P13P0Config,
) -> dict[str, Any]:
    delta_path = (
        config.r1_run_root / "advance_right_candidate_delta.jsonl"
    )
    delta_rows = _read_jsonl(delta_path)
    delta_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in delta_rows
    }
    object_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in feature_dataset["object_rows"]
    }
    if set(delta_by_key) != set(object_by_key):
        raise ValueError("P13 feature and R1 label object sets differ")

    candidate_ids_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in feature_dataset["feature_rows"]:
        key = (str(row["case_key"]), str(row["object_id"]))
        candidate_ids_by_key[key].append(str(row["candidate_road_id"]))
    candidate_labels: list[dict[str, Any]] = []
    object_labels: list[dict[str, Any]] = []
    for key in sorted(object_by_key):
        case_key, object_id = key
        feature_object = object_by_key[key]
        delta = delta_by_key[key]
        candidate_ids = sorted(candidate_ids_by_key.get(key, []))
        if candidate_ids != sorted(delta["treatment_candidate_road_ids"]):
            raise ValueError("P13 feature candidate IDs differ from R1 delta")
        eligible = bool(delta["eligible"])
        oracle_reachable = bool(delta["treatment_oracle_hit"])
        access_valid = bool(feature_object["access_valid"])
        if eligible:
            truth_ids = sorted(
                road_id
                for road_id, hits in delta[
                    "treatment_truth_component_hits"
                ].items()
                if hits
            )
        else:
            truth_ids = []
        truth_set = set(truth_ids)
        selection_supervised = (
            access_valid
            and eligible
            and oracle_reachable
            and bool(candidate_ids)
        )
        safety_supervised = (
            access_valid
            and ((eligible and oracle_reachable) or not eligible)
            and bool(candidate_ids)
        )
        for road_id in candidate_ids:
            candidate_labels.append(
                {
                    "candidate_road_id": road_id,
                    "case_key": case_key,
                    "fold": int(delta["fold"]),
                    "object_id": object_id,
                    "schema_version": SCHEMA_VERSION,
                    "supervised": selection_supervised,
                    "target": (
                        bool(road_id in truth_set)
                        if selection_supervised
                        else None
                    ),
                }
            )
        object_labels.append(
            {
                "access_valid": access_valid,
                "candidate_count": len(candidate_ids),
                "case_key": case_key,
                "eligible": eligible,
                "fold": int(delta["fold"]),
                "object_id": object_id,
                "oracle_reachable": oracle_reachable,
                "review": not eligible,
                "safety_supervised": safety_supervised,
                "schema_version": SCHEMA_VERSION,
                "supervised": selection_supervised,
                "truth_candidate_road_ids": truth_ids,
                "truth_nonempty": bool(truth_ids),
                "truth_plan_type": str(delta["truth_plan_type"]),
            }
        )
    candidate_labels.sort(key=_candidate_key)
    object_labels.sort(key=_row_key)
    return {
        "candidate_labels": candidate_labels,
        "label_inputs": [
            _input_record(
                delta_path,
                "R1_CANDIDATE_ORACLE_LABEL_ONLY",
            ),
            _input_record(
                config.p12r_run_root / "p12r_manifest.json",
                "P12R_LINEAGE_LABEL_ONLY",
            ),
            _input_record(
                config.p12r_run_root / "advance_right_realization_truth.jsonl",
                "P12R_TRUTH_LABEL_ONLY",
            ),
        ],
        "object_labels": object_labels,
    }


def build_examples(
    feature_dataset: Mapping[str, Any],
    labels: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidate_label_by_key = {
        (
            str(row["case_key"]),
            str(row["object_id"]),
            str(row["candidate_road_id"]),
        ): row
        for row in labels["candidate_labels"]
    }
    object_label_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in labels["object_labels"]
    }
    feature_by_object: dict[tuple[str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for row in feature_dataset["feature_rows"]:
        key = (str(row["case_key"]), str(row["object_id"]))
        feature_by_object[key].append(row)
    examples = []
    for key in sorted(object_label_by_key):
        label = object_label_by_key[key]
        rows = sorted(
            feature_by_object.get(key, []),
            key=lambda row: str(row["candidate_road_id"]),
        )
        candidates = []
        for row in rows:
            candidate_key = (
                key[0],
                key[1],
                str(row["candidate_road_id"]),
            )
            target_row = candidate_label_by_key[candidate_key]
            candidates.append(
                {
                    "bundle_id": str(row["bundle_id"]),
                    "candidate_road_id": str(row["candidate_road_id"]),
                    "feature_values": list(row["feature_values"]),
                    "target": target_row["target"],
                }
            )
        examples.append({**label, "candidates": candidates})
    return examples


def _case_feature_rows(
    *,
    case_key: str,
    skeleton: Mapping[str, Any],
    t01_roads: Sequence[Any],
    t01_nodes: Mapping[str, Point],
    raw_roads: Sequence[Any],
    candidates: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
    object_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    t01_by_id = {road.road_id: road for road in t01_roads}
    raw_by_id = {road.road_id: road for road in raw_roads}
    segment_by_id = {
        str(row["segment_id"]): row
        for row in skeleton.get("segments") or []
    }
    object_by_id = {
        str(row["object_id"]): row for row in object_rows
    }
    evidence_by_key = {
        (str(row["object_id"]), str(row["bundle_id"])): row
        for row in evidence_rows
    }
    candidate_by_object: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in candidates:
        candidate_by_object[str(row["object_id"])].append(row)

    feature_rows = []
    output_objects = []
    for object_id in sorted(object_by_id):
        object_row = object_by_id[object_id]
        segment = segment_by_id[object_id]
        object_candidates = sorted(
            candidate_by_object.get(object_id, []),
            key=lambda row: str(row["candidate_road_id"]),
        )
        source_owner, source_node_id = _parse_access(
            segment.get("source_segment_access")
        )
        target_owner, target_node_id = _parse_access(
            segment.get("target_segment_access")
        )
        source_point = t01_nodes.get(source_node_id)
        target_point = t01_nodes.get(target_node_id)
        swsd_geometry = _segment_geometry(segment, t01_by_id)
        control_ids = set(object_row["control_candidate_road_ids"])
        endpoint_ids = set(object_row["treatment_candidate_road_ids"]).difference(
            control_ids
        )
        bundle_ids = {
            str(row["bundle_id"]) for row in object_candidates
        }
        raw_values = []
        for candidate in object_candidates:
            road = raw_by_id[str(candidate["candidate_road_id"])]
            evidence = evidence_by_key.get(
                (object_id, str(candidate["bundle_id"]))
            )
            raw_values.append(
                _raw_candidate_metrics(
                    road=road,
                    swsd_geometry=swsd_geometry,
                    source_point=source_point,
                    target_point=target_point,
                    evidence=evidence,
                )
            )
        ranks = {
            "swsd": _ranks(
                [row["road_to_swsd_distance_m"] for row in raw_values]
            ),
            "forward": _ranks(
                [row["forward_access_cost_m"] for row in raw_values]
            ),
            "length": _ranks([row["road_length_m"] for row in raw_values]),
        }
        for index, candidate in enumerate(object_candidates):
            road = raw_by_id[str(candidate["candidate_road_id"])]
            evidence = evidence_by_key.get(
                (object_id, str(candidate["bundle_id"]))
            )
            metrics = raw_values[index]
            values = _feature_values(
                candidate=candidate,
                evidence=evidence,
                metrics=metrics,
                access_valid=bool(
                    object_row["access_valid_for_candidate"]
                ),
                same_owner=bool(source_owner == target_owner),
                candidate_count=len(object_candidates),
                control_count=len(control_ids),
                endpoint_count=len(endpoint_ids),
                bundle_count=len(bundle_ids),
                ranks=(
                    ranks["swsd"][index],
                    ranks["forward"][index],
                    ranks["length"][index],
                ),
                road=road,
            )
            if len(values) != len(FEATURE_NAMES):
                raise ValueError("P13 feature dimension differs")
            feature_rows.append(
                {
                    "bundle_id": str(candidate["bundle_id"]),
                    "candidate_road_id": str(candidate["candidate_road_id"]),
                    "case_key": case_key,
                    "feature_values": values,
                    "object_id": object_id,
                    "schema_version": SCHEMA_VERSION,
                }
            )
        output_objects.append(
            {
                "access_valid": bool(
                    object_row["access_valid_for_candidate"]
                ),
                "candidate_road_ids": [
                    str(row["candidate_road_id"])
                    for row in object_candidates
                ],
                "case_key": case_key,
                "object_id": object_id,
                "schema_version": SCHEMA_VERSION,
                "source_owner_present": bool(source_owner),
                "target_owner_present": bool(target_owner),
            }
        )
    return feature_rows, output_objects


def _raw_candidate_metrics(
    *,
    road: Any,
    swsd_geometry: Any,
    source_point: Point | None,
    target_point: Point | None,
    evidence: Mapping[str, Any] | None,
) -> dict[str, float | None]:
    start = Point(road.geometry.coords[0])
    end = Point(road.geometry.coords[-1])
    road_length = float(road.geometry.length)
    endpoint_distance = float(start.distance(end))
    start_source = _point_distance(start, source_point)
    end_source = _point_distance(end, source_point)
    start_target = _point_distance(start, target_point)
    end_target = _point_distance(end, target_point)
    forward_cost = _sum_optional(start_source, end_target)
    reverse_cost = _sum_optional(start_target, end_source)
    return {
        "road_length_m": road_length,
        "road_endpoint_distance_m": endpoint_distance,
        "road_straightness": (
            endpoint_distance / road_length if road_length > 0 else 0.0
        ),
        "road_to_swsd_distance_m": float(
            road.geometry.distance(swsd_geometry)
        ),
        "road_to_swsd_hausdorff_m": float(
            road.geometry.hausdorff_distance(swsd_geometry)
        ),
        "start_to_source_access_m": start_source,
        "end_to_source_access_m": end_source,
        "start_to_target_access_m": start_target,
        "end_to_target_access_m": end_target,
        "forward_access_cost_m": forward_cost,
        "reverse_access_cost_m": reverse_cost,
        "best_owner_distance_m": _evidence_value(
            evidence,
            "best_owner_carrier_distance_m",
        ),
        "forward_source_distance_m": _evidence_value(
            evidence,
            "forward_source_distance_m",
        ),
        "forward_target_distance_m": _evidence_value(
            evidence,
            "forward_target_distance_m",
        ),
        "reverse_source_distance_m": _evidence_value(
            evidence,
            "reverse_source_distance_m",
        ),
        "reverse_target_distance_m": _evidence_value(
            evidence,
            "reverse_target_distance_m",
        ),
    }


def _feature_values(
    *,
    candidate: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
    metrics: Mapping[str, float | None],
    access_valid: bool,
    same_owner: bool,
    candidate_count: int,
    control_count: int,
    endpoint_count: int,
    bundle_count: int,
    ranks: tuple[float, float, float],
    road: Any,
) -> list[float]:
    sources = set(candidate.get("candidate_sources") or [])
    orientation = str(candidate.get("orientation") or "MISSING")
    bundle_road_ids = list(
        [] if evidence is None else evidence["bundle_road_ids"]
    )
    control_bundle_ids = list(
        [] if evidence is None else evidence["control_road_ids_in_bundle"]
    )
    edges = list([] if evidence is None else evidence["geometric_edges"])
    source_boundaries = set(
        [] if evidence is None else evidence["source_boundary_node_ids"]
    )
    target_boundaries = set(
        [] if evidence is None else evidence["target_boundary_node_ids"]
    )
    source_incident = list(
        [] if evidence is None else evidence["source_incident_carrier_road_ids"]
    )
    target_incident = list(
        [] if evidence is None else evidence["target_incident_carrier_road_ids"]
    )
    road_id = str(candidate["candidate_road_id"])
    indegree = sum(
        str(edge["right_road_id"]) == road_id for edge in edges
    )
    outdegree = sum(
        str(edge["left_road_id"]) == road_id for edge in edges
    )
    return [
        float("LOCAL_5M" in sources),
        float("ENDPOINT_JUNCTION" in sources),
        float(bool(candidate.get("endpoint_evidence_complete"))),
        float(orientation == "FORWARD"),
        float(orientation == "REVERSE"),
        float(orientation == "SAME_OWNER"),
        float(orientation == "AMBIGUOUS"),
        float(orientation == "UNRESOLVED"),
        float(orientation == "MISSING"),
        float(access_valid),
        float(same_owner),
        _log_count(candidate_count),
        _log_count(control_count),
        _log_count(endpoint_count),
        _log_count(bundle_count),
        _log_count(len(bundle_road_ids) or 1),
        _log_count(len(control_bundle_ids)),
        _log_count(len(edges)),
        _log_count(
            sum(edge["relation"] == "SEQUENTIAL_GAP" for edge in edges)
        ),
        _log_count(
            sum(edge["relation"] == "PARALLEL_ENDPOINTS" for edge in edges)
        ),
        _log_count(len(source_boundaries)),
        _log_count(len(target_boundaries)),
        _log_count(len(source_incident)),
        _log_count(len(target_incident)),
        _log_distance(metrics["road_length_m"]),
        _log_distance(metrics["road_endpoint_distance_m"]),
        float(metrics["road_straightness"] or 0.0),
        _log_distance(metrics["road_to_swsd_distance_m"]),
        _log_distance(metrics["road_to_swsd_hausdorff_m"]),
        _log_distance(metrics["start_to_source_access_m"]),
        _log_distance(metrics["end_to_source_access_m"]),
        _log_distance(metrics["start_to_target_access_m"]),
        _log_distance(metrics["end_to_target_access_m"]),
        _log_distance(metrics["forward_access_cost_m"]),
        _log_distance(metrics["reverse_access_cost_m"]),
        _log_distance(metrics["best_owner_distance_m"]),
        _log_distance(metrics["forward_source_distance_m"]),
        _log_distance(metrics["forward_target_distance_m"]),
        _log_distance(metrics["reverse_source_distance_m"]),
        _log_distance(metrics["reverse_target_distance_m"]),
        float(metrics["best_owner_distance_m"] is None),
        float(not source_incident),
        float(not target_incident),
        float(road.snodeid in source_boundaries),
        float(road.enodeid in target_boundaries),
        _log_count(indegree),
        _log_count(outdegree),
        float(ranks[0]),
        float(ranks[1]),
        float(ranks[2]),
    ]


def _verify_artifact_manifest(root: Path) -> None:
    manifest = _read_json(root / "artifact_manifest.json")
    for row in manifest["artifacts"]:
        path = root / Path(str(row["path"])).name
        if not path.is_file():
            raise ValueError(f"R1 artifact is missing: {path}")
        if (
            sha256_file(path) != str(row["sha256"])
            or path.stat().st_size != int(row["size_bytes"])
        ):
            raise ValueError(f"R1 artifact hash differs: {path}")


def _input_record(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "role": role,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _deduplicate_inputs(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unique = {
        (str(row["role"]), str(row["path"])): dict(row) for row in rows
    }
    return [
        unique[key]
        for key in sorted(unique)
    ]


def _metric_projected(value: str) -> bool:
    from pyproj import CRS

    crs = CRS.from_user_input(value)
    return crs.is_projected and all(
        str(axis.unit_name or "").lower() in {"metre", "meter"}
        for axis in crs.axis_info[:2]
    )


def _point_distance(left: Point, right: Point | None) -> float | None:
    if right is None:
        return None
    value = float(left.distance(right))
    return value if math.isfinite(value) else None


def _sum_optional(
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None or right is None:
        return None
    return left + right


def _evidence_value(
    evidence: Mapping[str, Any] | None,
    name: str,
) -> float | None:
    if evidence is None or evidence.get(name) is None:
        return None
    value = float(evidence[name])
    return value if math.isfinite(value) else None


def _log_distance(value: float | None) -> float:
    if value is None:
        return math.log1p(1000.0)
    return math.log1p(min(max(0.0, float(value)), 1000.0))


def _log_count(value: int) -> float:
    return math.log1p(max(0, int(value)))


def _ranks(values: Sequence[float | None]) -> list[float]:
    if not values:
        return []
    order = sorted(
        range(len(values)),
        key=lambda index: (
            float("inf") if values[index] is None else float(values[index]),
            index,
        ),
    )
    denominator = max(1, len(values) - 1)
    result = [0.0] * len(values)
    for rank, index in enumerate(order):
        result[index] = rank / denominator
    return result


__all__ = [
    "FEATURE_NAMES",
    "attach_label_only_targets",
    "build_examples",
    "build_truth_free_feature_dataset",
]
