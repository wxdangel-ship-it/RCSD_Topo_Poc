from __future__ import annotations

import csv
import hashlib
import json
import math
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p7_models import (
    DECISION_AUDIT_NO_GO,
    EXPECTED_P5_DECISION,
    EXPECTED_P6_DECISION,
    SCHEME_A_P2_P3_P7_SCHEMA,
    SchemeAP2P3P7Config,
    choose_p7_decision,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p3_p7_audit(config: SchemeAP2P3P7Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)

    source = _load_sources(config)
    groups, seed_rows = _load_attributions(
        source["p6_paths"]["object_attributions"],
        config,
    )
    group_ids = set(groups)
    base, base_contract = _load_movement_free_base(
        source["evidence_paths"]["evidence"],
        source["evidence_paths"]["evidence_contract"],
        group_ids,
        config,
    )
    compatibility, compatibility_audit = _load_compatibility_adjacency(
        source["p2_p1_paths"]["compatibility_edges"],
        group_ids,
        groups,
    )
    geometry, geometry_adjacency, geometry_audit = _load_t01_geometry(
        source["dataset_p0_paths"]["module_artifact_inventory"],
        group_ids,
        groups,
        config.strict_hashes,
    )
    compatibility_features = aggregate_neighborhood(base, compatibility)
    geometry_neighbors = aggregate_neighborhood(geometry, geometry_adjacency)
    representations = _build_representations(
        groups,
        base,
        compatibility_features,
        geometry,
        geometry_neighbors,
        config,
    )
    feature_contract = _build_feature_contract(
        base_contract,
        config,
    )

    p6_summary = _read_json(source["p6_paths"]["summary"])
    neighborhood_audit = _build_neighborhood_audit(
        representations,
        groups,
        p6_summary,
        config,
    )
    calibration_audit = _build_calibration_audit(
        seed_rows,
        groups,
        config,
    )
    source_audit = _build_source_audit(
        source,
        base_contract,
        compatibility_audit,
        geometry_audit,
        groups,
        config,
    )

    representation_signature = _representation_signature(representations)
    source_gate = bool(source_audit["gate_pass"])
    build_gate = (
        len(representations) == config.expected_eligible_count
        and feature_contract["feature_count"] == config.representation_dimension
        and feature_contract["movement_feature_count"] == 0
        and feature_contract["truth_feature_count"] == 0
        and feature_contract["identifier_feature_count"] == 0
        and feature_contract["absolute_coordinate_feature_count"] == 0
        and all(
            len(row["features"]) == config.representation_dimension
            and all(math.isfinite(value) for value in row["features"])
            for row in representations
        )
    )
    representation_gate = bool(
        neighborhood_audit["stable_carrier_wrong_route_pass"]
    )
    calibration_contract_gate = bool(
        calibration_audit["contract_gate_pass"]
    )
    calibration_route_gate = bool(
        calibration_audit["calibration_only_route_pass"]
    )
    audit_gate = source_gate and build_gate and calibration_contract_gate

    deterministic_payload = {
        "source_lineage": source["lineage"],
        "representation_signature": representation_signature,
        "feature_contract": feature_contract,
        "compatibility_audit": compatibility_audit,
        "geometry_audit": geometry_audit,
        "neighborhood_audit": neighborhood_audit,
        "calibration_audit": calibration_audit,
        "source_audit": source_audit,
        "build_gate_pass": build_gate,
        "audit_gate_pass": audit_gate,
        "representation_gate_pass": representation_gate,
        "calibration_route_gate_pass": calibration_route_gate,
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

    decision = choose_p7_decision(
        audit_gate,
        representation_gate,
        calibration_route_gate,
    )
    run_root.mkdir(parents=True)
    paths = {
        "representations": run_root / "movement_free_representations.jsonl",
        "feature_contract": run_root / "feature_contract.json",
        "source_audit": run_root / "source_audit.json",
        "neighborhood_audit": run_root / "neighborhood_audit.json",
        "calibration_audit": run_root / "clue_calibration_audit.json",
        "summary": run_root / "scheme_a_p2_p3_p7_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_jsonl(paths["representations"], representations)
    write_json(paths["feature_contract"], feature_contract)
    write_json(paths["source_audit"], source_audit)
    write_json(paths["neighborhood_audit"], neighborhood_audit)
    write_json(paths["calibration_audit"], calibration_audit)

    summary = {
        "schema_version": SCHEME_A_P2_P3_P7_SCHEMA,
        "decision": decision,
        "preserved_p5_decision": EXPECTED_P5_DECISION,
        "input_p6_decision": EXPECTED_P6_DECISION,
        "audit_gate_pass": audit_gate,
        "source_gate_pass": source_gate,
        "build_gate_pass": build_gate,
        "representation_gate_pass": representation_gate,
        "calibration_contract_gate_pass": calibration_contract_gate,
        "calibration_route_gate_pass": calibration_route_gate,
        "resource_gate_pass": resource_gate,
        "reference_run_match": reference_match,
        "determinism_signature": signature,
        "representation_signature": representation_signature,
        "eligible_count": len(representations),
        "historical_base_dimension": config.historical_base_dimension,
        "excluded_movement_dimension_count": config.movement_dimension_count,
        "movement_free_base_dimension": config.base_dimension,
        "compatibility_dimension": config.compatibility_dimension,
        "geometry_dimension": config.geometry_dimension,
        "representation_dimension": config.representation_dimension,
        "stable_carrier_wrong_neighbor_audit": neighborhood_audit[
            "stable_carrier_wrong_neighbor_audit"
        ],
        "calibration_seed_audits": calibration_audit["seed_audits"],
        "source_lineage": source["lineage"],
        "resource": resource_metrics,
        "model_training_count": 0,
        "calibrator_fit_count": 0,
        "threshold_tuning_count": 0,
        "movement_feature_count": 0,
        "movement_decision_count": 0,
        "t03_t06_inference_feature_count": 0,
        "truth_inference_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "geometry_read_count": geometry_audit["geometry_read_count"],
        "geometry_write_count": 0,
        "coordinate_transform_count": 0,
        "crs": "EPSG:3857",
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(
        _render_report(summary, neighborhood_audit, calibration_audit),
        encoding="utf-8",
    )
    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p7_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P7_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "pre_t06_representation_calibration_audit_completed",
            "decision": decision,
            "preserved_p5_decision": EXPECTED_P5_DECISION,
            "input_p6_decision": EXPECTED_P6_DECISION,
            "determinism_signature": signature,
            "representation_signature": representation_signature,
            "reference_run_match": reference_match,
            "lineage": source["lineage"],
            "outputs": outputs,
            "model_training_count": 0,
            "calibrator_fit_count": 0,
            "threshold_tuning_count": 0,
            "movement_feature_count": 0,
            "t03_t06_inference_feature_count": 0,
            "geometry_read_count": geometry_audit["geometry_read_count"],
            "geometry_write_count": 0,
            "coordinate_transform_count": 0,
            "skeleton_mutation_count": 0,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p7-artifacts-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def aggregate_neighborhood(
    features: Mapping[str, Sequence[float]],
    adjacency: Mapping[str, set[str]],
) -> dict[str, tuple[float, ...]]:
    if not features:
        return {}
    dimension = len(next(iter(features.values())))
    result: dict[str, tuple[float, ...]] = {}
    for group_id, own_values in features.items():
        own = np.asarray(own_values, dtype=np.float64)
        neighbors = sorted(
            neighbor
            for neighbor in adjacency.get(group_id, set())
            if neighbor in features and neighbor != group_id
        )
        if not neighbors:
            result[group_id] = (0.0,) * (dimension * 2 + 1)
            continue
        matrix = np.asarray(
            [features[neighbor] for neighbor in neighbors],
            dtype=np.float64,
        )
        values = np.concatenate(
            (
                matrix.mean(axis=0) - own,
                matrix.std(axis=0),
                np.asarray([math.log1p(len(neighbors))]),
            )
        )
        result[group_id] = tuple(float(value) for value in values)
    return result


def relative_geometry_features(
    components: Sequence[Sequence[Sequence[float]]],
    *,
    pair_node_count: int,
    junction_node_count: int,
) -> tuple[float, ...]:
    clean = [
        [(float(point[0]), float(point[1])) for point in component]
        for component in components
        if len(component) >= 2
    ]
    lengths: list[float] = []
    spans: list[float] = []
    turns: list[float] = []
    orientations: list[tuple[float, float]] = []
    vertex_count = 0
    for component in clean:
        vertex_count += len(component)
        segment_lengths: list[float] = []
        segment_angles: list[float] = []
        for first, second in zip(component, component[1:]):
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            length = math.hypot(dx, dy)
            if length <= 0:
                continue
            angle = math.atan2(dy, dx)
            segment_lengths.append(length)
            segment_angles.append(angle)
            orientations.append((angle, length))
        component_length = sum(segment_lengths)
        if component_length <= 0:
            continue
        lengths.append(component_length)
        spans.append(
            math.hypot(
                component[-1][0] - component[0][0],
                component[-1][1] - component[0][1],
            )
        )
        for before, after in zip(segment_angles, segment_angles[1:]):
            delta = (after - before + math.pi) % (2 * math.pi) - math.pi
            turns.append(abs(delta))
    total_length = sum(lengths)
    total_span = sum(spans)
    mean_length = total_length / len(lengths) if lengths else 0.0
    turn_mean = sum(turns) / len(turns) if turns else 0.0
    turn_variance = (
        sum((value - turn_mean) ** 2 for value in turns) / len(turns)
        if turns
        else 0.0
    )
    orientation_weight = sum(weight for _, weight in orientations)
    if orientation_weight:
        cos_mean = sum(
            math.cos(2 * angle) * weight for angle, weight in orientations
        ) / orientation_weight
        sin_mean = sum(
            math.sin(2 * angle) * weight for angle, weight in orientations
        ) / orientation_weight
        axial_dispersion = 1.0 - math.hypot(cos_mean, sin_mean)
    else:
        axial_dispersion = 0.0
    return (
        math.log1p(total_length),
        math.log1p(max(lengths, default=0.0)),
        math.log1p(mean_length),
        math.log1p(len(lengths)),
        total_length / total_span if total_span > 0 else 0.0,
        turn_mean,
        max(turns, default=0.0),
        math.sqrt(turn_variance),
        axial_dispersion,
        math.log1p(vertex_count),
        math.log1p(pair_node_count),
        math.log1p(junction_node_count),
    )


def best_recall_one_threshold(
    *,
    probabilities: Sequence[float],
    targets: Sequence[bool],
    required_precision: float,
    required_macro_f1: float,
) -> dict[str, Any]:
    if len(probabilities) != len(targets) or not probabilities:
        raise ValueError("probability/target scope differs or is empty")
    positive_probabilities = [
        float(probability)
        for probability, target in zip(probabilities, targets, strict=True)
        if target
    ]
    if not positive_probabilities:
        raise ValueError("positive clue target is absent")
    threshold = min(positive_probabilities)
    predictions = [
        float(probability) >= threshold for probability in probabilities
    ]
    tp = sum(
        prediction and target
        for prediction, target in zip(predictions, targets, strict=True)
    )
    fp = sum(
        prediction and not target
        for prediction, target in zip(predictions, targets, strict=True)
    )
    fn = sum(
        not prediction and target
        for prediction, target in zip(predictions, targets, strict=True)
    )
    tn = len(targets) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    positive_f1 = _f1(precision, recall)
    negative_precision = tn / (tn + fn) if tn + fn else 1.0
    negative_recall = tn / (tn + fp) if tn + fp else 1.0
    negative_f1 = _f1(negative_precision, negative_recall)
    macro_f1 = (positive_f1 + negative_f1) / 2
    feasible = (
        math.isclose(recall, 1.0, abs_tol=1e-12)
        and precision >= required_precision
        and macro_f1 >= required_macro_f1
    )
    return {
        "threshold": threshold,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "macro_f1": macro_f1,
        "feasible": feasible,
    }


def _load_sources(config: SchemeAP2P3P7Config) -> dict[str, Any]:
    roots = {
        "p6": normalize_runtime_path(config.p6_run_root).resolve(strict=True),
        "dataset_p0": normalize_runtime_path(config.dataset_p0_root).resolve(
            strict=True
        ),
        "p2_p1": normalize_runtime_path(config.p2_p1_dataset_root).resolve(
            strict=True
        ),
        "evidence": normalize_runtime_path(
            config.structural_evidence_root
        ).resolve(strict=True),
    }
    manifest_paths = {
        "p6": roots["p6"] / "scheme_a_p2_p3_p6_manifest.json",
        "dataset_p0": roots["dataset_p0"] / "dataset_p0_manifest.json",
        "p2_p1": roots["p2_p1"] / "scheme_a_p2_p1_dataset_manifest.json",
        "evidence": roots["evidence"] / "scheme_a_p2_p2_p2_p0_manifest.json",
    }
    manifests = {key: _read_json(path) for key, path in manifest_paths.items()}
    paths = {
        key: _verified_outputs(manifest, config.strict_hashes)
        for key, manifest in manifests.items()
    }
    return {
        "roots": roots,
        "manifests": manifests,
        "p6_paths": paths["p6"],
        "dataset_p0_paths": paths["dataset_p0"],
        "p2_p1_paths": paths["p2_p1"],
        "evidence_paths": paths["evidence"],
        "lineage": {
            key: sha256_file(path) for key, path in manifest_paths.items()
        },
    }


def _load_attributions(
    path: Path,
    config: SchemeAP2P3P7Config,
) -> tuple[dict[str, dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    groups: dict[str, dict[str, Any]] = {}
    seed_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        seed = int(row["seed"])
        if seed not in config.expected_seeds:
            raise ValueError(f"unexpected seed: {seed}")
        seed_rows[seed].append(row)
        group_id = str(row["group_id"])
        stable = {
            "group_id": group_id,
            "case_key": str(row["case_key"]),
            "object_id": str(row["object_id"]),
            "fold": int(row["fold"]),
            "truth_target": str(row["truth_target"]),
            "clue_target": bool(row["clue_target"]),
            "review_target": bool(row["review_target"]),
        }
        previous = groups.setdefault(group_id, stable)
        if previous != stable:
            raise ValueError(f"seed attribution differs: {group_id}")
    if len(groups) != config.expected_eligible_count:
        raise ValueError("eligible attribution count differs")
    if any(
        len(seed_rows[seed]) != config.expected_eligible_count
        for seed in config.expected_seeds
    ):
        raise ValueError("per-seed attribution count differs")
    case_folds: dict[str, set[int]] = defaultdict(set)
    for row in groups.values():
        case_folds[row["case_key"]].add(row["fold"])
    if any(len(folds) != 1 for folds in case_folds.values()):
        raise ValueError("Case is split across folds")
    return groups, dict(seed_rows)


def _load_movement_free_base(
    evidence_path: Path,
    contract_path: Path,
    eligible: set[str],
    config: SchemeAP2P3P7Config,
) -> tuple[dict[str, tuple[float, ...]], dict[str, Any]]:
    contract = _read_json(contract_path)
    names = [str(name) for name in contract["feature_names"]]
    if len(names) != config.historical_base_dimension:
        raise ValueError("historical base dimension differs")
    excluded = [
        index for index, name in enumerate(names) if "MOVEMENT" in name
    ]
    if len(excluded) != config.movement_dimension_count:
        raise ValueError("Movement dimension count differs")
    keep = [index for index in range(len(names)) if index not in set(excluded)]
    values: dict[str, tuple[float, ...]] = {}
    excluded_nonzero_count = 0
    for row in _read_jsonl(evidence_path):
        group_id = str(row["group_id"])
        if group_id not in eligible:
            continue
        features = [float(value) for value in row["features"]]
        if len(features) != config.historical_base_dimension:
            raise ValueError("base evidence dimension differs")
        excluded_nonzero_count += sum(features[index] != 0.0 for index in excluded)
        if group_id in values:
            raise ValueError(f"duplicate base evidence: {group_id}")
        values[group_id] = tuple(features[index] for index in keep)
    if set(values) != eligible:
        raise ValueError("movement-free base scope differs")
    return values, {
        "historical_feature_count": len(names),
        "historical_declared_movement_feature_count": int(
            contract["movement_feature_count"]
        ),
        "excluded_movement_feature_count": len(excluded),
        "excluded_movement_feature_indices": excluded,
        "excluded_movement_feature_names": [names[index] for index in excluded],
        "excluded_movement_nonzero_value_count": excluded_nonzero_count,
        "movement_free_feature_names": [names[index] for index in keep],
        "movement_free_feature_count": len(keep),
        "allowed_modules": contract["allowed_modules"],
        "prohibited_modules": contract["prohibited_modules"],
        "t07_evidence_mode": contract["t07_evidence_mode"],
        "truth_feature_count": int(contract["truth_feature_count"]),
        "identifier_feature_count": int(contract["identifier_feature_count"]),
        "absolute_coordinate_feature_count": int(
            contract["absolute_coordinate_feature_count"]
        ),
    }


def _load_compatibility_adjacency(
    path: Path,
    eligible: set[str],
    groups: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, Any]]:
    node_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    row_count = 0
    truth_feature_count = 0
    for row in _read_jsonl(path):
        group_id = str(row["segment_group_id"])
        if group_id not in eligible:
            continue
        case_key = str(row["case_key"])
        if case_key != str(groups[group_id]["case_key"]):
            raise ValueError("compatibility Case lineage differs")
        row_count += 1
        truth_feature_count += bool(row.get("feature_uses_truth"))
        node_groups[(case_key, str(row["node_group_id"]))].add(group_id)
    adjacency = {group_id: set() for group_id in eligible}
    for (_, _), linked in node_groups.items():
        for group_id in linked:
            adjacency[group_id].update(linked - {group_id})
    cross_case_count = sum(
        str(groups[group_id]["case_key"])
        != str(groups[neighbor]["case_key"])
        for group_id, neighbors in adjacency.items()
        for neighbor in neighbors
    )
    return adjacency, {
        "compatibility_edge_row_count": row_count,
        "shared_node_context_count": len(node_groups),
        "groups_with_neighbor_count": sum(bool(value) for value in adjacency.values()),
        "directed_neighbor_link_count": sum(map(len, adjacency.values())),
        "cross_case_neighbor_count": cross_case_count,
        "truth_feature_count": truth_feature_count,
    }


def _load_t01_geometry(
    inventory_path: Path,
    eligible: set[str],
    groups: Mapping[str, Mapping[str, Any]],
    strict_hashes: bool,
) -> tuple[
    dict[str, tuple[float, ...]],
    dict[str, set[str]],
    dict[str, Any],
]:
    by_object = {
        (str(row["case_key"]), str(row["object_id"])): group_id
        for group_id, row in groups.items()
    }
    case_paths: dict[str, tuple[Path, str]] = {}
    prohibited_inference_rows = 0
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            module = str(row["module"])
            model_input = str(row["model_input"]).lower() == "true"
            if module in {"T03", "T04", "T05", "T06"} and model_input:
                prohibited_inference_rows += 1
            if row["artifact_role"] != "t01_segment" or not model_input:
                continue
            case_key = f"{row['family']}:{row['business_id']}"
            path = normalize_runtime_path(row["path"]).resolve(strict=True)
            expected_hash = str(row["sha256"])
            if strict_hashes and sha256_file(path) != expected_hash:
                raise ValueError(f"T01 hash mismatch: {case_key}")
            if case_key in case_paths:
                raise ValueError(f"duplicate T01 Case path: {case_key}")
            case_paths[case_key] = (path, expected_hash)

    geometry: dict[str, tuple[float, ...]] = {}
    node_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    crs_values: set[str] = set()
    geometry_read_count = 0
    for case_key, (path, _) in sorted(case_paths.items()):
        if not any(row["case_key"] == case_key for row in groups.values()):
            continue
        with fiona.open(path) as source:
            geometry_read_count += 1
            crs_value = source.crs.to_string() if source.crs else ""
            crs_values.add(crs_value)
            if crs_value != "EPSG:3857":
                raise ValueError(f"unexpected T01 CRS: {case_key}={crs_value}")
            for feature in source:
                properties = dict(feature["properties"])
                object_id = str(properties.get("id") or "")
                group_id = by_object.get((case_key, object_id))
                if group_id not in eligible:
                    continue
                components = _geometry_components(feature["geometry"])
                pair_nodes = _split_ids(properties.get("pair_nodes"))
                junction_nodes = _split_ids(properties.get("junc_nodes"))
                geometry[group_id] = relative_geometry_features(
                    components,
                    pair_node_count=len(pair_nodes),
                    junction_node_count=len(junction_nodes),
                )
                for node_id in sorted(set(pair_nodes + junction_nodes)):
                    node_groups[(case_key, node_id)].add(group_id)
    adjacency = {group_id: set() for group_id in eligible}
    for (_, _), linked in node_groups.items():
        for group_id in linked:
            adjacency[group_id].update(linked - {group_id})
    cross_case_count = sum(
        str(groups[group_id]["case_key"])
        != str(groups[neighbor]["case_key"])
        for group_id, neighbors in adjacency.items()
        for neighbor in neighbors
    )
    return geometry, adjacency, {
        "eligible_geometry_count": len(geometry),
        "missing_geometry_count": len(eligible - set(geometry)),
        "t01_case_path_count": len(case_paths),
        "geometry_read_count": geometry_read_count,
        "crs_values": sorted(crs_values),
        "shared_node_context_count": len(node_groups),
        "groups_with_neighbor_count": sum(bool(value) for value in adjacency.values()),
        "directed_neighbor_link_count": sum(map(len, adjacency.values())),
        "cross_case_neighbor_count": cross_case_count,
        "prohibited_t03_t06_model_input_row_count": prohibited_inference_rows,
        "geometry_write_count": 0,
        "coordinate_transform_count": 0,
    }


def _build_representations(
    groups: Mapping[str, Mapping[str, Any]],
    base: Mapping[str, Sequence[float]],
    compatibility: Mapping[str, Sequence[float]],
    geometry: Mapping[str, Sequence[float]],
    geometry_neighbors: Mapping[str, Sequence[float]],
    config: SchemeAP2P3P7Config,
) -> list[dict[str, Any]]:
    if not (
        set(groups)
        == set(base)
        == set(compatibility)
        == set(geometry)
        == set(geometry_neighbors)
    ):
        raise ValueError("representation component scope differs")
    rows = []
    for group_id in sorted(groups):
        values = (
            tuple(base[group_id])
            + tuple(compatibility[group_id])
            + tuple(geometry[group_id])
            + tuple(geometry_neighbors[group_id])
        )
        if len(values) != config.representation_dimension:
            raise ValueError(f"representation dimension differs: {group_id}")
        rows.append(
            {
                "schema_version": SCHEME_A_P2_P3_P7_SCHEMA,
                "group_id": group_id,
                "case_key": groups[group_id]["case_key"],
                "object_id": groups[group_id]["object_id"],
                "fold": groups[group_id]["fold"],
                "identifier_role": "lineage_only",
                "feature_uses_truth": False,
                "feature_uses_identifier": False,
                "absolute_coordinate_feature_count": 0,
                "movement_feature_count": 0,
                "features": [float(value) for value in values],
            }
        )
    return rows


def _build_feature_contract(
    base: Mapping[str, Any],
    config: SchemeAP2P3P7Config,
) -> dict[str, Any]:
    base_names = list(base["movement_free_feature_names"])
    geometry_names = [
        "t01_geometry_log_total_length",
        "t01_geometry_log_max_component_length",
        "t01_geometry_log_mean_component_length",
        "t01_geometry_log_component_count",
        "t01_geometry_sinuosity",
        "t01_geometry_mean_absolute_turn",
        "t01_geometry_max_absolute_turn",
        "t01_geometry_std_absolute_turn",
        "t01_geometry_axial_orientation_dispersion",
        "t01_geometry_log_vertex_count",
        "t01_geometry_log_pair_node_count",
        "t01_geometry_log_junction_node_count",
    ]
    names = (
        base_names
        + [f"compat_neighbor_mean_minus_self:{name}" for name in base_names]
        + [f"compat_neighbor_std:{name}" for name in base_names]
        + ["compat_neighbor_log_degree"]
        + geometry_names
        + [f"geometry_neighbor_mean_minus_self:{name}" for name in geometry_names]
        + [f"geometry_neighbor_std:{name}" for name in geometry_names]
        + ["geometry_neighbor_log_degree"]
    )
    if len(names) != config.representation_dimension:
        raise ValueError("feature contract dimension differs")
    return {
        "schema_version": SCHEME_A_P2_P3_P7_SCHEMA,
        "feature_count": len(names),
        "feature_names": names,
        "historical_base_feature_count": base["historical_feature_count"],
        "excluded_movement_feature_count": base[
            "excluded_movement_feature_count"
        ],
        "excluded_movement_feature_indices": base[
            "excluded_movement_feature_indices"
        ],
        "excluded_movement_feature_names": base[
            "excluded_movement_feature_names"
        ],
        "excluded_movement_nonzero_value_count": base[
            "excluded_movement_nonzero_value_count"
        ],
        "movement_free_base_feature_count": config.base_dimension,
        "compatibility_feature_count": config.compatibility_dimension,
        "relative_geometry_feature_count": config.geometry_dimension,
        "movement_feature_count": 0,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "t03_t06_inference_feature_count": 0,
        "movement_source_role": "EXCLUDED_BY_USER_AUTHORIZATION",
        "identifier_role": "LINEAGE_JOIN_ONLY",
        "geometry_contract": "TRANSLATION_ROTATION_INVARIANT_NO_COORDINATE_OUTPUT",
        "t07_evidence_mode": base["t07_evidence_mode"],
        "prohibited_modules": base["prohibited_modules"],
    }


def _build_neighborhood_audit(
    representations: Sequence[Mapping[str, Any]],
    groups: Mapping[str, Mapping[str, Any]],
    p6_summary: Mapping[str, Any],
    config: SchemeAP2P3P7Config,
) -> dict[str, Any]:
    row_by_group = {str(row["group_id"]): row for row in representations}
    stable_fp = list(
        p6_summary["clue_summary"]["stable_false_positive_group_ids"]
    )
    stable_fn = list(
        p6_summary["clue_summary"]["stable_false_negative_group_ids"]
    )
    stable_wrong = list(
        p6_summary["clue_summary"][
            "stable_carrier_wrong_accepted_group_ids"
        ]
    )
    query_ids = sorted(set(stable_fp + stable_fn + stable_wrong))
    audits = []
    held_out_case_neighbor_count = 0
    for group_id in query_ids:
        query = groups[group_id]
        neighbors = _nearest_neighbors(
            group_id,
            row_by_group,
            groups,
            config.nearest_neighbor_count,
        )
        held_out_case_neighbor_count += sum(
            row["case_key"] == query["case_key"] for row in neighbors
        )
        audits.append(
            {
                "group_id": group_id,
                "case_key": query["case_key"],
                "fold": query["fold"],
                "query_truth_target": query["truth_target"],
                "query_clue_target": query["clue_target"],
                "neighbor_count": len(neighbors),
                "neighbor_clue_true_count": sum(
                    row["clue_target"] for row in neighbors
                ),
                "neighbor_clue_false_count": sum(
                    not row["clue_target"] for row in neighbors
                ),
                "neighbor_truth_target_counts": dict(
                    sorted(Counter(row["truth_target"] for row in neighbors).items())
                ),
                "neighbors": neighbors,
            }
        )
    wrong_audits = [
        row for row in audits if row["group_id"] in set(stable_wrong)
    ]
    route_pass = bool(wrong_audits) and all(
        row["neighbor_truth_target_counts"].get("KEEP_SWSD", 0) >= 1
        and row["neighbor_clue_true_count"] >= 1
        for row in wrong_audits
    )
    return {
        "stable_false_positive_group_ids": stable_fp,
        "stable_false_negative_group_ids": stable_fn,
        "stable_carrier_wrong_group_ids": stable_wrong,
        "query_group_count": len(query_ids),
        "held_out_case_neighbor_count": held_out_case_neighbor_count,
        "stable_group_neighbor_audits": audits,
        "stable_carrier_wrong_neighbor_audit": wrong_audits,
        "stable_carrier_wrong_route_pass": route_pass,
        "required_keep_swsd_neighbor_count": 1,
        "required_clue_true_neighbor_count": 1,
    }


def _nearest_neighbors(
    query_group: str,
    representations: Mapping[str, Mapping[str, Any]],
    groups: Mapping[str, Mapping[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    held_out_fold = int(groups[query_group]["fold"])
    training_ids = sorted(
        group_id
        for group_id, row in groups.items()
        if int(row["fold"]) != held_out_fold
    )
    matrix = np.asarray(
        [representations[group_id]["features"] for group_id in training_ids],
        dtype=np.float64,
    )
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales[scales <= 1e-6] = 1.0
    query = np.asarray(
        representations[query_group]["features"],
        dtype=np.float64,
    )
    distances = np.sqrt(np.mean(((matrix - query) / scales) ** 2, axis=1))
    order = np.argsort(distances, kind="stable")[:count]
    result = []
    for rank, index in enumerate(order, start=1):
        group_id = training_ids[int(index)]
        result.append(
            {
                "rank": rank,
                "group_id": group_id,
                "case_key": groups[group_id]["case_key"],
                "distance": float(distances[int(index)]),
                "clue_target": groups[group_id]["clue_target"],
                "truth_target": groups[group_id]["truth_target"],
            }
        )
    return result


def _build_calibration_audit(
    seed_rows: Mapping[int, Sequence[Mapping[str, Any]]],
    groups: Mapping[str, Mapping[str, Any]],
    config: SchemeAP2P3P7Config,
) -> dict[str, Any]:
    pool_audits = []
    case_fold = {
        str(row["case_key"]): int(row["fold"]) for row in groups.values()
    }
    for seed in config.expected_seeds:
        rows = [row for row in seed_rows[seed] if not row["review_target"]]
        for outer_fold in range(config.expected_fold_count):
            pool = [row for row in rows if int(row["fold"]) != outer_fold]
            held_out_cases = {
                case for case, fold in case_fold.items() if fold == outer_fold
            }
            positive = sum(bool(row["clue_target"]) for row in pool)
            negative = len(pool) - positive
            leaked = sum(
                str(row["case_key"]) in held_out_cases for row in pool
            )
            pool_audits.append(
                {
                    "seed": seed,
                    "outer_fold": outer_fold,
                    "pool_count": len(pool),
                    "positive_count": positive,
                    "negative_count": negative,
                    "held_out_case_contribution_count": leaked,
                    "case_grouped": leaked == 0,
                    "pool_gate_pass": (
                        positive >= config.calibration_min_positive
                        and negative >= config.calibration_min_negative
                        and leaked == 0
                    ),
                }
            )
    seed_audits = []
    for seed in config.expected_seeds:
        rows = [row for row in seed_rows[seed] if not row["review_target"]]
        audit = best_recall_one_threshold(
            probabilities=[float(row["clue_probability"]) for row in rows],
            targets=[bool(row["clue_target"]) for row in rows],
            required_precision=config.required_clue_precision,
            required_macro_f1=config.required_clue_macro_f1,
        )
        seed_audits.append({"seed": seed, **audit})
    contract_gate = all(row["pool_gate_pass"] for row in pool_audits)
    route_pass = all(row["feasible"] for row in seed_audits)
    return {
        "contract": {
            "fit_scope": "INNER_VALIDATION_CASE_GROUPED_ONLY",
            "evaluation_scope": "OUTER_HELD_OUT_CASE_ONLY",
            "carrier_rank_decoupled": True,
            "calibrator_fit_count": 0,
            "threshold_tuning_count": 0,
            "required_min_positive": config.calibration_min_positive,
            "required_min_negative": config.calibration_min_negative,
            "required_recall": config.required_clue_recall,
            "required_precision": config.required_clue_precision,
            "required_macro_f1": config.required_clue_macro_f1,
        },
        "pool_audits": pool_audits,
        "seed_audits": seed_audits,
        "contract_gate_pass": contract_gate,
        "calibration_only_route_pass": route_pass,
    }


def _build_source_audit(
    source: Mapping[str, Any],
    base: Mapping[str, Any],
    compatibility: Mapping[str, Any],
    geometry: Mapping[str, Any],
    groups: Mapping[str, Any],
    config: SchemeAP2P3P7Config,
) -> dict[str, Any]:
    manifests = source["manifests"]
    checks = {
        "p6_decision": manifests["p6"].get("decision") == EXPECTED_P6_DECISION,
        "p6_preserved_p5": manifests["p6"].get("preserved_p5_decision")
        == EXPECTED_P5_DECISION,
        "dataset_p0_decision": manifests["dataset_p0"].get("decision")
        == "P05_SCHEME_A_DATASET_P0_GO",
        "p2_p1_dataset_status": manifests["p2_p1"].get("status")
        == "dataset_passed",
        "p2_p1_truth_feature_zero": int(
            manifests["p2_p1"].get("truth_feature_count", -1)
        )
        == 0,
        "structural_evidence_decision": manifests["evidence"].get("decision")
        == "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO",
        "eligible_count": len(groups) == config.expected_eligible_count,
        "movement_exclusion_count": base["excluded_movement_feature_count"]
        == config.movement_dimension_count,
        "movement_free_base_count": base["movement_free_feature_count"]
        == config.base_dimension,
        "compatibility_truth_free": compatibility["truth_feature_count"] == 0,
        "compatibility_case_local": compatibility["cross_case_neighbor_count"] == 0,
        "geometry_complete": geometry["eligible_geometry_count"]
        == config.expected_eligible_count,
        "geometry_missing_zero": geometry["missing_geometry_count"] == 0,
        "geometry_crs": geometry["crs_values"] == ["EPSG:3857"],
        "geometry_case_local": geometry["cross_case_neighbor_count"] == 0,
        "prohibited_t03_t06_input_zero": geometry[
            "prohibited_t03_t06_model_input_row_count"
        ]
        == 0,
        "geometry_write_zero": geometry["geometry_write_count"] == 0,
        "coordinate_transform_zero": geometry["coordinate_transform_count"] == 0,
    }
    return {
        "checks": checks,
        "gate_pass": all(checks.values()),
        "source_lineage": source["lineage"],
        "historical_contract_metadata_conflict": {
            "declared_movement_feature_count": base[
                "historical_declared_movement_feature_count"
            ],
            "actual_movement_named_dimension_count": base[
                "excluded_movement_feature_count"
            ],
            "resolution": (
                "P7_EXCLUDES_ACTUAL_MOVEMENT_DIMENSIONS_"
                "HISTORICAL_ARTIFACT_UNCHANGED"
            ),
        },
        "compatibility": dict(compatibility),
        "geometry": dict(geometry),
    }


def _geometry_components(geometry: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    if geometry is None:
        return ()
    kind = str(geometry["type"])
    coordinates = geometry["coordinates"]
    if kind == "LineString":
        coordinates = [coordinates]
    if kind != "MultiLineString":
        raise ValueError(f"unsupported T01 geometry: {kind}")
    return tuple(
        tuple((float(point[0]), float(point[1])) for point in component)
        for component in coordinates
    )


def _split_ids(value: Any) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    ]


def _representation_signature(
    rows: Sequence[Mapping[str, Any]],
) -> str:
    digest = hashlib.sha256()
    for row in rows:
        payload = {
            "group_id": row["group_id"],
            "features": row["features"],
        }
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _verified_outputs(
    manifest: Mapping[str, Any],
    strict_hashes: bool,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for key, value in dict(manifest.get("outputs") or {}).items():
        record = dict(value or {})
        path = normalize_runtime_path(str(record.get("path") or "")).resolve(
            strict=True
        )
        if path.stat().st_size != int(record.get("size_bytes") or -1):
            raise ValueError(f"output size mismatch: {key}")
        if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"output hash mismatch: {key}")
        result[str(key)] = path
    return result


def _reference_match(reference_root: Path | None, signature: str) -> bool | None:
    if reference_root is None:
        return None
    root = normalize_runtime_path(reference_root).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p7_manifest.json")
    return str(manifest.get("determinism_signature") or "") == signature


def _render_report(
    summary: Mapping[str, Any],
    neighborhood: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> str:
    wrong = neighborhood["stable_carrier_wrong_neighbor_audit"][0]
    lines = [
        "# P05-Scheme-A-P2-P3-P7 验证报告",
        "",
        f"- decision: `{summary['decision']}`",
        f"- signature: `{summary['determinism_signature']}`",
        f"- representation: `{summary['representation_dimension']}` dimensions",
        f"- Movement features: `{summary['movement_feature_count']}`",
        f"- representation route pass: `{summary['representation_gate_pass']}`",
        f"- calibration-only route pass: `{summary['calibration_route_gate_pass']}`",
        "",
        "## 稳定 carrier wrong 的训练邻域",
        "",
        f"- group: `{wrong['group_id']}`",
        f"- truth targets: `{wrong['neighbor_truth_target_counts']}`",
        f"- clue=true: `{wrong['neighbor_clue_true_count']}` / `{wrong['neighbor_count']}`",
        "",
        "## 单调 Clue 阈值诊断",
        "",
        "| seed | threshold | recall | precision | macro-F1 | feasible |",
        "|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in calibration["seed_audits"]:
        lines.append(
            f"| {row['seed']} | {row['threshold']:.12f} | "
            f"{row['recall']:.10f} | {row['precision']:.10f} | "
            f"{row['macro_f1']:.10f} | {row['feasible']} |"
        )
    return "\n".join(lines) + "\n"


def _f1(precision: float, recall: float) -> float:
    return (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            text = line.strip()
            if text:
                yield dict(json.loads(text))


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    dict(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "aggregate_neighborhood",
    "best_recall_one_threshold",
    "relative_geometry_features",
    "run_scheme_a_p2_p3_p7_audit",
]
