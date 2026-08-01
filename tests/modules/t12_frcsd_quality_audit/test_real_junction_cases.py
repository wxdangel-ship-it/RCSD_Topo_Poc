from __future__ import annotations

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


T03_DATA = _host_path(r"E:\TestData\POC_Data\T03")
T03_ERROR_DATA = _host_path(r"E:\TestData\POC_Data\T03_Error")
T03_VALIDATION_WORK = _host_path(
    r"E:\Work\RCSD_Topo_Poc__wt_t03_quality_closure_20260730"
    r"\outputs\_work\t03_t05_ownership_surface_connectivity_20260731"
)
T03_RUN = T03_VALIDATION_WORK / "final_replay_v3" / "t03" / "final"
T03_ERROR_RUN = (
    T03_VALIDATION_WORK / "final_replay_v3" / "t03_error" / "final"
)
REAL_DATA_AVAILABLE = all(
    path.exists()
    for path in (T03_DATA, T03_ERROR_DATA, T03_RUN, T03_ERROR_RUN)
)


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


@pytest.mark.skipif(
    not REAL_DATA_AVAILABLE,
    reason="local T03/T03_Error real-data evidence is unavailable",
)
def test_four_positive_and_sixteen_negative_real_cases() -> None:
    t03_source = load_junction_sources(
        t03_run_root=T03_RUN,
        t07_step3_run_root=None,
    )
    error_source = load_junction_sources(
        t03_run_root=T03_ERROR_RUN,
        t07_step3_run_root=None,
    )
    positive_ids = {
        "520394575",
        "622700016",
        "522008569",
        "522806716",
    }
    negative_ids = {
        "40338648",
        "613826647",
        "12777955",
        "523923800",
        "991243",
        "1514722",
        "1881692",
        "507831701",
        "520691911",
        "922217",
        "54265667",
        "502058682",
        "950770",
        "994202",
        "53679574",
        "620658564",
    }
    confirmed: set[str] = set()
    confirmed_types: dict[str, str] = {}
    evaluated: set[str] = set()
    decisions: dict[str, str] = {}
    for data_root, source in (
        (T03_DATA, t03_source),
        (T03_ERROR_DATA, error_source),
    ):
        for case in source.t03_cases:
            if case.case_id not in positive_ids | negative_ids:
                continue
            result = _audit_case(
                data_root=data_root,
                source=source,
                case=case,
            )
            evaluated.add(case.case_id)
            if result.confirmed:
                confirmed.add(case.case_id)
                confirmed_types[case.case_id] = result.confirmed[0]["issue_type"]
            elif result.exclusions:
                decisions[case.case_id] = result.exclusions[0]["decision_rule"]
            else:
                decisions[case.case_id] = next(
                    iter(result.audit["source_exclusions"]),
                    "not_a_rejected_candidate",
                )

    rejected_source_ids = {
        case.case_id
        for source in (t03_source, error_source)
        for case in source.t03_cases
    }
    assert "523923800" not in rejected_source_ids
    assert confirmed == positive_ids
    assert confirmed_types == {
        "520394575": "junction_unmatched_support_topology",
        "622700016": "junction_unmatched_support_topology",
        "522008569": "junction_required_topology_missing",
        "522806716": "junction_required_topology_missing",
    }
    assert not (confirmed & negative_ids)
    assert evaluated | {"523923800"} >= positive_ids | negative_ids
    assert decisions["613826647"] == "constraint_induced_split"
    assert decisions["950770"] == "invalid_input_geometry"
    assert decisions["12777955"] == "not_all_targets_terminal_endpoint"
