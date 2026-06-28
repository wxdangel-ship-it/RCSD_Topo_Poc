from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import write_feature_triplet
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_aware_plan_release import (
    T05_SEMANTIC_JUNCTION_RELEASE_REASON,
    _release_trigger_for_mapping,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_semantic_junction_groups import (
    STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS,
    STEP3_SEMANTIC_JUNCTION_GROUPS_STEM,
    build_semantic_junction_groups,
    discover_intersection_match_path,
    downgrade_semantic_junction_topology_rows,
    refresh_semantic_junction_topology_audit,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import feature
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
)


def test_t05_relation_builds_semantic_group_and_downgrades_junction_fail(tmp_path: Path) -> None:
    step2_root = tmp_path / "step2_extract_rcsd_segments"
    step2_root.mkdir()
    relation_path = step2_root / "intersection_match_all.geojson"
    relation_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"target_id": "A", "base_id": "R", "status": 0},
                        "geometry": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (step2_root / "t06_step2_summary.json").write_text(
        json.dumps({"input_paths": {"intersection_match_path": str(relation_path)}}),
        encoding="utf-8",
    )
    replaceable_path = step2_root / "t06_rcsd_segment_replaceable.gpkg"
    replaceable_path.write_text("", encoding="utf-8")

    frcsd_nodes = [
        feature({"id": "A", "source": 2}, Point(0, 0)),
        feature({"id": "R", "mainnodeid": "R", "source": 1}, Point(120, 0)),
    ]
    relation_rows = [
        feature(
            {
                "swsd_segment_id": "A_B",
                "relation_status": "replaced+retained_swsd",
                "source_mix": "source_1+source_2",
                "swsd_pair_nodes": ["A", "B"],
                "swsd_junc_nodes": [],
                "swsd_to_frcsd_node_map": [
                    {"swsd_node_id": "A", "frcsd_node_ids": ["R"], "mapping_status": "mapped"}
                ],
            },
            Point(0, 0),
        )
    ]

    group_rows, stats = build_semantic_junction_groups(
        step2_replaceable_path=replaceable_path,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=relation_rows,
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    assert stats["semantic_junction_group_count"] == 1
    props = group_rows[0]["properties"]
    assert props["semantic_junction_group_id"] == "SJG:R"
    assert props["swsd_node_ids"] == ["A"]
    assert props["rcsd_node_ids"] == ["R"]
    assert props["max_pairwise_distance_m"] == 120.0
    assert frcsd_nodes[0]["properties"]["semantic_junction_group_id"] == "SJG:R"
    assert frcsd_nodes[1]["properties"]["semantic_junction_group_id"] == "SJG:R"

    topology_rows = [
        feature(
            {
                "audit_layer": "segment_junction_connectivity",
                "audit_status": "fail",
                "audit_reason": "junction_incident_segment_mapped_points_diverged",
                "swsd_node_id": "A",
                "action": "",
                "action_reason": "",
            },
            Point(0, 0),
        )
    ]
    downgrade_stats = downgrade_semantic_junction_topology_rows(topology_rows, group_rows)
    downgraded = topology_rows[0]["properties"]
    assert downgrade_stats == {"semantic_junction_topology_fail_downgraded_count": 1}
    assert downgraded["audit_status"] == "warn"
    assert downgraded["audit_reason"] == "junction_incident_semantic_group_diverged"
    assert downgraded["action"] == "semantic_junction_group_verified"
    assert downgraded["action_reason"] == "semantic_junction_group_id=SJG:R"


def test_many_target_to_one_base_uses_one_semantic_group(tmp_path: Path) -> None:
    step2_root = tmp_path / "step2_extract_rcsd_segments"
    step2_root.mkdir()
    relation_path = step2_root / "intersection_match_all.geojson"
    relation_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"target_id": "A", "base_id": "R", "status": 0}, "geometry": None},
                    {"type": "Feature", "properties": {"target_id": "C", "base_id": "R", "status": 0}, "geometry": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    (step2_root / "t06_step2_summary.json").write_text(
        json.dumps({"input_paths": {"intersection_match_path": str(relation_path)}}),
        encoding="utf-8",
    )
    replaceable_path = step2_root / "t06_rcsd_segment_replaceable.gpkg"
    replaceable_path.write_text("", encoding="utf-8")

    frcsd_nodes = [
        feature({"id": "A", "source": 2}, Point(0, 0)),
        feature({"id": "C", "source": 2}, Point(0, 10)),
        feature({"id": "R", "source": 1}, Point(100, 0)),
    ]
    relation_rows = [
        feature({"swsd_segment_id": "A_C", "swsd_pair_nodes": ["A", "C"], "swsd_junc_nodes": []}, None)
    ]

    group_rows, _stats = build_semantic_junction_groups(
        step2_replaceable_path=replaceable_path,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=relation_rows,
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    assert len(group_rows) == 1
    props = group_rows[0]["properties"]
    assert props["semantic_junction_group_id"] == "SJG:R"
    assert props["swsd_node_ids"] == ["A", "C"]
    assert props["rcsd_node_ids"] == ["R"]


def test_downgrade_requires_failed_nodes_inside_semantic_group() -> None:
    group_rows = [
        feature(
            {
                "semantic_junction_group_id": "SJG:R",
                "swsd_node_ids": ["A"],
                "frcsd_node_ids": ["A", "R"],
            },
            None,
        )
    ]
    topology_rows = [
        feature(
            {
                "audit_layer": "segment_junction_connectivity",
                "audit_status": "fail",
                "audit_reason": "junction_incident_segment_mapped_points_diverged",
                "swsd_node_id": "A",
                "frcsd_node_ids": ["A", "OTHER"],
                "action": "",
                "action_reason": "",
            },
            None,
        )
    ]

    stats = downgrade_semantic_junction_topology_rows(topology_rows, group_rows)

    assert stats == {"semantic_junction_topology_fail_downgraded_count": 0}
    assert topology_rows[0]["properties"]["audit_status"] == "fail"


def test_t05_relation_release_ignores_distance_gate() -> None:
    trigger = _release_trigger_for_mapping(
        {},
        swsd_node_id="A",
        rcsd_node_id="R",
        swsd_points={"A": Point(0, 0)},
        rcsd_points={"R": Point(1, 0)},
        surface_status={},
        swsd_anchor_nodes=set(),
        t05_relation_by_target={"A": "R"},
        rcsd_semantic_ids_by_node={"R": {"R"}},
    )

    assert trigger is not None
    assert trigger["ok"] is True
    assert trigger["surface_status"][1] == T05_SEMANTIC_JUNCTION_RELEASE_REASON


def test_discover_intersection_match_path_resolves_cli_relative_path_from_cwd(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    step2_root = tmp_path / "run" / "step2_extract_rcsd_segments"
    relation_path = repo_root / "outputs" / "baseline" / "intersection_match_all.geojson"
    step2_root.mkdir(parents=True)
    relation_path.parent.mkdir(parents=True)
    relation_path.write_text("{}", encoding="utf-8")
    (step2_root / "t06_step2_summary.json").write_text(
        json.dumps({"input_paths": {"intersection_match_path": "outputs/baseline/intersection_match_all.geojson"}}),
        encoding="utf-8",
    )
    replaceable_path = step2_root / "t06_rcsd_segment_replaceable.gpkg"
    replaceable_path.write_text("", encoding="utf-8")
    monkeypatch.chdir(repo_root)

    assert discover_intersection_match_path(replaceable_path) == relation_path.resolve()


def test_discover_intersection_match_path_keeps_summary_relative_fallback(tmp_path: Path, monkeypatch) -> None:
    step2_root = tmp_path / "step2_extract_rcsd_segments"
    other_cwd = tmp_path / "other"
    relation_path = step2_root / "intersection_match_all.geojson"
    step2_root.mkdir()
    other_cwd.mkdir()
    relation_path.write_text("{}", encoding="utf-8")
    (step2_root / "t06_step2_summary.json").write_text(
        json.dumps({"input_paths": {"intersection_match_path": "intersection_match_all.geojson"}}),
        encoding="utf-8",
    )
    replaceable_path = step2_root / "t06_rcsd_segment_replaceable.gpkg"
    replaceable_path.write_text("", encoding="utf-8")
    monkeypatch.chdir(other_cwd)

    assert discover_intersection_match_path(replaceable_path) == relation_path.resolve()


def test_refresh_semantic_junction_topology_audit_rewrites_surface_output(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    group_rows = [
        feature(
            {
                "semantic_junction_group_id": "SJG:R",
                "swsd_node_ids": ["A"],
                "frcsd_node_ids": ["A", "R"],
            },
            Point(0, 0),
        )
    ]
    topology_rows = [
        feature(
            {
                "audit_layer": "segment_junction_connectivity",
                "audit_status": "fail",
                "audit_reason": "junction_incident_segment_mapped_points_diverged",
                "swsd_node_id": "A",
                "frcsd_node_ids": ["A", "R"],
                "action": "",
                "action_reason": "",
            },
            Point(0, 0),
        )
    ]
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_SEMANTIC_JUNCTION_GROUPS_STEM,
        features=group_rows,
        fieldnames=STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS,
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        features=topology_rows,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    )
    summary_path = step_root / "t06_step3_summary.json"
    summary_path.write_text(json.dumps({"existing": 1}), encoding="utf-8")

    stats = refresh_semantic_junction_topology_audit(step_root=step_root, summary_path=summary_path)

    refreshed_payload = json.loads((step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.json").read_text(encoding="utf-8"))
    refreshed = refreshed_payload["features"][0]["properties"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert stats == {"semantic_junction_topology_fail_downgraded_count": 1}
    assert refreshed["audit_status"] == "warn"
    assert refreshed["audit_reason"] == "junction_incident_semantic_group_diverged"
    assert summary["semantic_junction_topology_fail_downgraded_count"] == 1
    assert summary["topology_connectivity_fail_count"] == 0
    assert summary["topology_connectivity_warn_count"] == 1
