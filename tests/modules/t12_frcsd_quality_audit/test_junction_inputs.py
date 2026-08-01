from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_inputs import (
    load_junction_sources,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_t03_chain(root: Path, *, complete: bool = True) -> None:
    case = root / "cases" / "100"
    _write_json(
        case / "step3_status.json",
        {
            "case_id": "100",
            "target_group_node_ids": ["100", "101"],
        },
    )
    _write_json(
        case / "step6_status.json",
        {
            "case_id": "100",
            "association_class": "B",
            "association_state": "not_established",
        },
    )
    _write_json(case / "step6_audit.json", {})
    _write_json(
        case / "step7_status.json",
        {"case_id": "100", "step7_state": "rejected"},
    )
    if complete:
        _write_json(case / "step7_audit.json", {})


def _write_t07_step2(root: Path, *, summary_fail2_count: int = 2) -> Path:
    step2 = root / "step2_anchor_recognition"
    step2.mkdir(parents=True, exist_ok=True)
    nodes = gpd.GeoDataFrame(
        {
            "id": ["j1", "j1m", "j2", "j3"],
            "mainnodeid": ["j1", "j1", "j2", "j3"],
            "is_anchor": ["fail1", "", "fail2", "fail2"],
            "kind_2": [4, 4, 4, 8],
            "geometry": [Point(0, 0), Point(1, 0), Point(10, 0), Point(11, 0)],
        },
        crs="EPSG:3857",
    )
    nodes.to_file(step2 / "nodes.gpkg", layer="nodes", driver="GPKG")
    error1 = gpd.GeoDataFrame(
        {
            "error_type": ["node_error_1", "node_error_1"],
            "junction_id": ["j1", "j2"],
            "representative_node_id": ["j1", "j2"],
            "intersection_ids": ["b1,b2", "b3"],
            "geometry": [Point(0, 0), Point(10, 0)],
        },
        crs="EPSG:3857",
    )
    error1.to_file(
        step2 / "node_error_1.gpkg",
        layer="node_error_1",
        driver="GPKG",
    )
    error2 = gpd.GeoDataFrame(
        {
            "error_type": ["node_error_2", "node_error_2"],
            "junction_id": ["j2", "j3"],
            "representative_node_id": ["j2", "j3"],
            "intersection_ids": ["b3", "b3"],
            "geometry": [Point(10, 0), Point(11, 0)],
        },
        crs="EPSG:3857",
    )
    error2.to_file(
        step2 / "node_error_2.gpkg",
        layer="node_error_2",
        driver="GPKG",
    )
    _write_json(
        step2 / "t07_step2_summary.json",
        {
            "run_id": "t07",
            "anchor_fail1_count": 1,
            "anchor_fail2_count": summary_fail2_count,
        },
    )
    pd.DataFrame(
        [
            {
                "target_id": "j1",
                "relation_source": "T07_STEP2",
                "relation_state": "multiple_intersections_for_group",
                "matched_rcsdintersection_ids": "b1|b2",
            },
            {
                "target_id": "j2",
                "relation_source": "T07_STEP2",
                "relation_state": "intersection_shared_by_multiple_groups",
                "matched_rcsdintersection_ids": "b3",
            },
            {
                "target_id": "j3",
                "relation_source": "T07_STEP2",
                "relation_state": "intersection_shared_by_multiple_groups",
                "matched_rcsdintersection_ids": "b3",
            },
        ]
    ).to_csv(step2 / "t07_swsd_rcsd_relation_evidence.csv", index=False)
    return step2


def test_t03_rejected_formal_chain_and_t07_step2_failures_are_loaded(
    tmp_path: Path,
) -> None:
    t03 = tmp_path / "t03"
    _write_t03_chain(t03)
    t07 = tmp_path / "t07"
    _write_t07_step2(t07)

    sources = load_junction_sources(
        t03_run_root=t03,
        t07_run_root=t07,
        t07_step3_run_root=None,
    )

    assert [case.case_id for case in sources.t03_cases] == ["100"]
    assert sources.t03_cases[0].association_status["association_class"] == "B"
    assert len(sources.t07_rows) == 2
    assert {row["failure_type"] for row in sources.t07_rows} == {"fail1", "fail2"}
    fail2 = next(row for row in sources.t07_rows if row["failure_type"] == "fail2")
    assert fail2["related_target_ids"] == ["j2", "j3"]
    assert fail2["base_ids"] == ["b3"]
    assert sources.audit["t03"]["artifact_count"] == 5
    assert sources.audit["t07"]["source_kind"] == "t07_step2_final_anchor_failure"
    assert sources.audit["t07"]["relation_evidence_validated_failure_count"] == 3
    assert sources.audit["t07"]["step3_cardinality_import_count"] == 0
    assert sources.audit["silent_fix"] is False


def test_t07_fail2_final_state_overrides_provisional_fail1(tmp_path: Path) -> None:
    t07 = tmp_path / "t07"
    _write_t07_step2(t07)

    sources = load_junction_sources(
        t03_run_root=None,
        t07_run_root=t07,
        t07_step3_run_root=None,
    )

    fail1_targets = {
        row["target_id"]
        for row in sources.t07_rows
        if row["failure_type"] == "fail1"
    }
    fail2_targets = {
        target_id
        for row in sources.t07_rows
        if row["failure_type"] == "fail2"
        for target_id in row["related_target_ids"]
    }
    assert fail1_targets == {"j1"}
    assert fail2_targets == {"j2", "j3"}
    assert fail1_targets.isdisjoint(fail2_targets)


def test_t07_step2_summary_mismatch_is_blocked(tmp_path: Path) -> None:
    t07 = tmp_path / "t07"
    _write_t07_step2(t07, summary_fail2_count=1)

    with pytest.raises(T12ContractError, match="fail2 count mismatch"):
        load_junction_sources(
            t03_run_root=None,
            t07_run_root=t07,
            t07_step3_run_root=None,
        )


def test_t07_step2_relation_evidence_mismatch_is_blocked(tmp_path: Path) -> None:
    t07 = tmp_path / "t07"
    step2 = _write_t07_step2(t07)
    evidence_path = step2 / "t07_swsd_rcsd_relation_evidence.csv"
    evidence = pd.read_csv(evidence_path, dtype=str).fillna("")
    evidence.loc[evidence["target_id"] == "j3", "matched_rcsdintersection_ids"] = "b4"
    evidence.to_csv(evidence_path, index=False)

    with pytest.raises(T12ContractError, match="relation evidence IDs mismatch"):
        load_junction_sources(
            t03_run_root=None,
            t07_run_root=t07,
            t07_step3_run_root=None,
        )


def test_step3_cardinality_rows_are_never_imported(tmp_path: Path) -> None:
    t07 = tmp_path / "t07"
    _write_t07_step2(t07)
    step3 = tmp_path / "t07_step3"
    _write_json(
        step3 / "relation_cardinality_errors.json",
        {
            "rows": [
                {
                    "error_type": "many_target_to_one_base",
                    "target_id": "764857|607990665",
                    "base_id": "5885140164809953",
                },
                {
                    "error_type": "many_target_to_one_base",
                    "target_id": "26981804|601184240",
                    "base_id": "5885208313528543",
                },
            ]
        },
    )

    sources = load_junction_sources(
        t03_run_root=None,
        t07_run_root=t07,
        t07_step3_run_root=step3,
    )

    assert all(
        false_id not in str(row)
        for false_id in ("764857", "26981804")
        for row in sources.t07_rows
    )
    assert sources.audit["t07"]["step3_cardinality_import_count"] == 0


def test_deprecated_step3_parameter_only_locates_sibling_step2(tmp_path: Path) -> None:
    run_root = tmp_path / "t10_run"
    t07 = run_root / "t07_step12" / "t07_step12"
    step2 = _write_t07_step2(t07)
    step3 = (
        run_root
        / "t07_step3_intersection_match"
        / "t07_step3"
        / "step3_intersection_match"
    )
    step3.mkdir(parents=True)

    sources = load_junction_sources(
        t03_run_root=None,
        t07_run_root=None,
        t07_step3_run_root=step3,
    )

    assert sources.audit["t07"]["step2_run_root"] == str(step2.resolve())
    assert sources.audit["t07"]["deprecated_step3_locator_used"] is True
    assert sources.audit["t07"]["step3_cardinality_import_count"] == 0


def test_t03_internal_full_input_sibling_step3_root_is_loaded(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "t03_internal_full_input"
    t03 = out_root / "t03_full"
    _write_t03_chain(t03)
    (t03 / "cases" / "100" / "step3_status.json").unlink()
    internal_root = out_root / "_internal" / "t03_full"
    step3_root = internal_root / "step3_runs" / "t03_full__step3"
    _write_json(
        step3_root / "cases" / "100" / "step3_status.json",
        {
            "case_id": "100",
            "target_group_node_ids": ["100", "101"],
        },
    )
    internal_manifest = internal_root / "t03_internal_full_input_manifest.json"
    _write_json(
        internal_manifest,
        {
            "run_root": str(t03),
            "step3_run_root": str(step3_root),
        },
    )

    sources = load_junction_sources(
        t03_run_root=t03,
        t07_run_root=None,
        t07_step3_run_root=None,
    )

    assert [case.case_id for case in sources.t03_cases] == ["100"]
    assert sources.audit["t03"]["step3_run_root"] == str(step3_root.resolve())
    assert "t03_internal_full_input_manifest.json" in sources.audit["t03"][
        "identity_artifacts"
    ]


def test_incomplete_t03_rejected_chain_is_blocked(tmp_path: Path) -> None:
    t03 = tmp_path / "t03"
    _write_t03_chain(t03, complete=False)

    with pytest.raises(T12ContractError, match="incomplete formal audit chains"):
        load_junction_sources(
            t03_run_root=t03,
            t07_run_root=None,
            t07_step3_run_root=None,
        )
