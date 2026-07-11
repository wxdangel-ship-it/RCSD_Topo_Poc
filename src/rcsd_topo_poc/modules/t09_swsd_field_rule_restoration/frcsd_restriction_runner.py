from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import frcsd_restriction as _facade


def T09FrcsdRestrictionArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T09FrcsdRestrictionArtifacts(*args, **kwargs)


def T09FrcsdRestrictionRunResult(*args: Any, **kwargs: Any) -> Any:
    return _facade.T09FrcsdRestrictionRunResult(*args, **kwargs)


def _build_arm_carriers(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_arm_carriers(*args, **kwargs)


def _build_frcsd_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_frcsd_roads(*args, **kwargs)


def _build_node_aliases(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_node_aliases(*args, **kwargs)


def _build_restriction_features(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_restriction_features(*args, **kwargs)


def _build_v2_restriction_features(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_v2_restriction_features(*args, **kwargs)


def _default_run_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._default_run_id(*args, **kwargs)


def _feature_json(*args: Any, **kwargs: Any) -> Any:
    return _facade._feature_json(*args, **kwargs)


def _filter_rules_for_strategy(*args: Any, **kwargs: Any) -> Any:
    return _facade._filter_rules_for_strategy(*args, **kwargs)


def _read_records_with_audit(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_records_with_audit(*args, **kwargs)


def _road_refs_by_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_refs_by_id(*args, **kwargs)


def _runtime_environment(*args: Any, **kwargs: Any) -> Any:
    return _facade._runtime_environment(*args, **kwargs)


def _summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._summary(*args, **kwargs)


def _write_csv(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_csv(*args, **kwargs)


def normalize_restoration_strategy(*args: Any, **kwargs: Any) -> Any:
    return _facade.normalize_restoration_strategy(*args, **kwargs)


def write_gpkg(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_gpkg(*args, **kwargs)


def write_json(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_json(*args, **kwargs)


def run_t09_frcsd_restriction_modeling(
    *,
    arms_path: str | Path,
    movements_path: str | Path,
    restored_rules_path: str | Path,
    frcsd_road_path: str | Path,
    frcsd_node_path: str | Path,
    segment_relation_path: str | Path,
    output_dir: str | Path,
    run_id: str | None = None,
    arms_layer: str | None = None,
    movements_layer: str | None = None,
    restored_rules_layer: str | None = None,
    frcsd_road_layer: str | None = None,
    frcsd_node_layer: str | None = None,
    segment_relation_layer: str | None = None,
    target_epsg: int = 3857,
    strategy_version: str | _facade.RestorationStrategy = _facade.RestorationStrategy.RESTRICTION_ONLY_V1,
) -> T09FrcsdRestrictionRunResult:
    started = time.perf_counter()
    strategy = normalize_restoration_strategy(strategy_version)
    effective_run_id = run_id or _default_run_id()
    out_dir = Path(output_dir).expanduser().resolve() / effective_run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    input_started = time.perf_counter()
    arms_read = _read_records_with_audit(
        arms_path,
        layer_name=arms_layer,
        target_epsg=target_epsg,
        geometry_optional=True,
    )
    movements_read = _read_records_with_audit(
        movements_path,
        layer_name=movements_layer,
        target_epsg=target_epsg,
        geometry_optional=True,
    )
    rules_read = _read_records_with_audit(
        restored_rules_path,
        layer_name=restored_rules_layer,
        target_epsg=target_epsg,
        geometry_optional=True,
    )
    road_read = _read_records_with_audit(
        frcsd_road_path,
        layer_name=frcsd_road_layer,
        target_epsg=target_epsg,
    )
    node_read = _read_records_with_audit(
        frcsd_node_path,
        layer_name=frcsd_node_layer,
        target_epsg=target_epsg,
    )
    relation_read = _read_records_with_audit(
        segment_relation_path,
        layer_name=segment_relation_layer,
        target_epsg=target_epsg,
    )
    input_read_seconds = time.perf_counter() - input_started
    arms = arms_read.records
    movements = movements_read.records
    loaded_rules = rules_read.records
    frcsd_road_records = road_read.records
    frcsd_node_records = node_read.records
    segment_relations = relation_read.records
    rules, strategy_skipped = _filter_rules_for_strategy(
        rules=loaded_rules,
        strategy=strategy,
    )

    carrier_started = time.perf_counter()
    frcsd_roads = _build_frcsd_roads(frcsd_road_records)
    road_by_ref = {road.ref: road for road in frcsd_roads}
    road_refs_by_id = _road_refs_by_id(frcsd_roads)
    node_aliases = _build_node_aliases(frcsd_node_records)
    carriers = _build_arm_carriers(
        arms=arms,
        segment_relations=segment_relations,
        road_by_ref=road_by_ref,
        road_refs_by_id=road_refs_by_id,
        node_aliases=node_aliases,
        strict_audit=strategy == _facade.RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    carrier_build_seconds = time.perf_counter() - carrier_started
    decision_started = time.perf_counter()
    candidates: list[dict[str, Any]] = []
    if strategy == _facade.RestorationStrategy.RESTRICTION_ONLY_V1:
        features, skipped = _build_restriction_features(
            rules=rules,
            movements=movements,
            carriers=carriers,
            road_by_ref=road_by_ref,
        )
        stable_fields = _facade.FRCSDS_RESTRICTION_FIELDS
    else:
        features, candidates, skipped = _build_v2_restriction_features(
            rules=rules,
            movements=movements,
            carriers=carriers,
            road_by_ref=road_by_ref,
            expected_strategy=strategy,
        )
        stable_fields = _facade.FRCSDS_RESTRICTION_V2_FIELDS
    skipped.update(strategy_skipped)
    decision_modeling_seconds = time.perf_counter() - decision_started

    artifacts = T09FrcsdRestrictionArtifacts(
        output_dir=out_dir,
        frcsd_restriction_gpkg=out_dir / f"{_facade.FRCSDS_RESTRICTION_STEM}.gpkg",
        frcsd_restriction_csv=out_dir / f"{_facade.FRCSDS_RESTRICTION_STEM}.csv",
        frcsd_restriction_json=out_dir / f"{_facade.FRCSDS_RESTRICTION_STEM}.json",
        frcsd_restriction_candidates_gpkg=out_dir / f"{_facade.FRCSDS_RESTRICTION_CANDIDATE_STEM}.gpkg",
        frcsd_restriction_candidates_csv=out_dir / f"{_facade.FRCSDS_RESTRICTION_CANDIDATE_STEM}.csv",
        frcsd_restriction_candidates_json=out_dir / f"{_facade.FRCSDS_RESTRICTION_CANDIDATE_STEM}.json",
        summary_json=out_dir / _facade.FRCSDS_RESTRICTION_SUMMARY,
    )
    output_started = time.perf_counter()
    write_gpkg(
        artifacts.frcsd_restriction_gpkg,
        features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=stable_fields,
        geometry_type="LineString",
    )
    _write_csv(artifacts.frcsd_restriction_csv, (item["properties"] for item in features), stable_fields)
    write_json(
        artifacts.frcsd_restriction_json,
        {
            "row_count": len(features),
            "features": [_feature_json(item, crs_text=f"EPSG:{target_epsg}") for item in features],
        },
    )
    if strategy == _facade.RestorationStrategy.MULTI_EVIDENCE_V2:
        write_gpkg(
            artifacts.frcsd_restriction_candidates_gpkg,
            (item for item in candidates if item.get("geometry") is not None),
            crs_text=f"EPSG:{target_epsg}",
            empty_fields=_facade.FRCSDS_RESTRICTION_CANDIDATE_FIELDS,
            geometry_type="LineString",
        )
        _write_csv(
            artifacts.frcsd_restriction_candidates_csv,
            (item["properties"] for item in candidates),
            _facade.FRCSDS_RESTRICTION_CANDIDATE_FIELDS,
        )
        write_json(
            artifacts.frcsd_restriction_candidates_json,
            {
                "row_count": len(candidates),
                "gpkg_geometry_row_count": sum(
                    1 for item in candidates if item.get("geometry") is not None
                ),
                "features": [
                    _feature_json(item, crs_text=f"EPSG:{target_epsg}")
                    for item in candidates
                ],
            },
        )

    output_write_seconds = time.perf_counter() - output_started
    elapsed_seconds = time.perf_counter() - started
    summary = _summary(
        run_id=effective_run_id,
        target_epsg=target_epsg,
        elapsed_seconds=elapsed_seconds,
        input_paths={
            "arms_path": arms_path,
            "movements_path": movements_path,
            "restored_rules_path": restored_rules_path,
            "frcsd_road_path": frcsd_road_path,
            "frcsd_node_path": frcsd_node_path,
            "segment_relation_path": segment_relation_path,
        },
        input_audit={
            "arms": arms_read.audit,
            "movements": movements_read.audit,
            "restored_rules": rules_read.audit,
            "frcsd_roads": road_read.audit,
            "frcsd_nodes": node_read.audit,
            "segment_relations": relation_read.audit,
        },
        input_counts={
            "arms": len(arms),
            "movements": len(movements),
            "restored_rules": len(loaded_rules),
            "accepted_strategy_rules": len(rules),
            "frcsd_roads": len(frcsd_road_records),
            "frcsd_nodes": len(frcsd_node_records),
            "segment_relations": len(segment_relations),
        },
        carriers=carriers,
        restrictions=features,
        candidates=candidates,
        skipped=skipped,
        strategy=strategy,
        stage_timings={
            "read_inputs_seconds": input_read_seconds,
            "build_carriers_seconds": carrier_build_seconds,
            "model_rules_seconds": decision_modeling_seconds,
            "write_artifacts_before_summary_seconds": output_write_seconds,
            "run_before_summary_write_seconds": elapsed_seconds,
        },
        runtime_environment=_runtime_environment(),
        output_paths={
            "frcsd_restriction_gpkg": artifacts.frcsd_restriction_gpkg,
            "frcsd_restriction_csv": artifacts.frcsd_restriction_csv,
            "frcsd_restriction_json": artifacts.frcsd_restriction_json,
            **(
                {
                    "frcsd_restriction_candidates_gpkg": artifacts.frcsd_restriction_candidates_gpkg,
                    "frcsd_restriction_candidates_csv": artifacts.frcsd_restriction_candidates_csv,
                    "frcsd_restriction_candidates_json": artifacts.frcsd_restriction_candidates_json,
                }
                if strategy == _facade.RestorationStrategy.MULTI_EVIDENCE_V2
                else {}
            ),
            "summary_json": artifacts.summary_json,
        },
    )
    write_json(artifacts.summary_json, summary)
    return T09FrcsdRestrictionRunResult(
        artifacts=artifacts,
        summary=summary,
        restriction_count=len(features),
        candidate_count=len(candidates),
    )
