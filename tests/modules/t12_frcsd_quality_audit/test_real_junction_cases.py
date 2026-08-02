from __future__ import annotations

import csv
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import LoadedInputs
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_audit import (
    audit_junction_quality,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_inputs import (
    JunctionSources,
    T03CaseEvidence,
    load_junction_sources,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import AuditConfig


def _host_path(value: str) -> Path:
    if os.name == "nt":
        return Path(value)
    drive, remainder = value.split(":", 1)
    return Path(f"/mnt/{drive.lower()}{remainder.replace(chr(92), '/')}")


QA_DATA = _host_path(r"E:\TestData\POC_QA\T03_Error")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
QA_T03_RUN = Path(
    os.environ.get(
        "T12_QA_T03_RUN",
        str(
            REPOSITORY_ROOT
            / "outputs"
            / "_work"
            / "t03_accuracy_closure_20260801"
            / "scheme_a_replay_v1"
            / "qa_t03_error_final"
        ),
    )
)
QA_TRUTH = (
    Path(__file__).parent
    / "data"
    / "t12_qa_junction_truth_20260802.csv"
)
QA_SNAPSHOT_SHA256 = (
    "9bfea7042a5b208522b137099bc1ed35d6da8a03393819074c58e8f3d71be765"
)
REAL_DATA_AVAILABLE = QA_DATA.exists() and QA_T03_RUN.exists()


def _audit_case(
    *,
    data_root: Path,
    source: JunctionSources,
    case: T03CaseEvidence,
):
    case_root = data_root / case.case_id
    nodes = gpd.read_file(case_root / "nodes.gpkg")
    roads = gpd.read_file(case_root / "roads.gpkg")
    frcsd_roads = gpd.read_file(case_root / "rcsdroad.gpkg")
    frcsd_nodes = gpd.read_file(case_root / "rcsdnode.gpkg")
    drivezone = gpd.read_file(case_root / "drivezone.gpkg")
    crs = str(nodes.crs)
    empty = gpd.GeoDataFrame(
        {
            "id": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )
    loaded = LoadedInputs(
        segments=empty,
        swsd_roads=roads,
        swsd_nodes=nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        rcsd_intersections=empty,
        drivezone=drivezone,
        t05_anchor_audit=pd.DataFrame(),
        t06_cross_evidence={},
        processing_crs=crs,
        crop_inner_geometry=None,
        input_audit={},
        topology_audit={},
        evidence_audit={},
    )
    single_source = JunctionSources(
        t03_cases=(case,),
        t07_rows=(),
        t03_eligibility_nodes_path=None,
        audit=source.audit,
    )
    return audit_junction_quality(
        loaded,
        single_source,
        AuditConfig(),
        run_id="real_case_regression",
    )


def _load_truth() -> list[dict[str, str]]:
    with QA_TRUTH.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_current_qa_truth_registry_is_snapshot_scoped() -> None:
    rows = _load_truth()
    assert len(rows) == 11
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert {row["dataset_snapshot"] for row in rows} == {"qa_t03_error"}
    assert {row["input_aggregate_sha256"] for row in rows} == {
        QA_SNAPSHOT_SHA256
    }
    assert {row["expected_verdict"] for row in rows} <= {
        "confirmed",
        "excluded",
        "source_excluded",
    }
    assert sum(row["expected_verdict"] == "confirmed" for row in rows) == 1
    assert all(row["decision_source"] == "current_raw_data_audit" for row in rows)
    assert all(row["evidence_reason"] for row in rows)


@pytest.mark.skipif(
    not REAL_DATA_AVAILABLE,
    reason="current QA T03 replay or source data is unavailable",
)
def test_current_qa_snapshot_junction_truth() -> None:
    source = load_junction_sources(
        t03_run_root=QA_T03_RUN,
        t07_step3_run_root=None,
    )
    truth_by_case = {row["case_id"]: row for row in _load_truth()}
    actual: dict[str, tuple[str, str, str]] = {}
    for case in source.t03_cases:
        if case.case_id not in truth_by_case:
            continue
        result = _audit_case(
            data_root=QA_DATA,
            source=source,
            case=case,
        )
        if result.confirmed:
            row = result.confirmed[0]
            actual[case.case_id] = (
                "confirmed",
                row["decision_rule"],
                row["issue_type"],
            )
        elif result.exclusions:
            row = result.exclusions[0]
            actual[case.case_id] = (
                "excluded",
                row["decision_rule"],
                "",
            )
        else:
            actual[case.case_id] = (
                "source_excluded",
                next(iter(result.audit["source_exclusions"]), ""),
                "",
            )

    assert set(actual) == set(truth_by_case)
    for case_id, truth in truth_by_case.items():
        assert actual[case_id] == (
            truth["expected_verdict"],
            truth["expected_decision_rule"],
            truth["expected_issue_type"],
        )
