from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, Polygon, mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RELATION_DIM,
    GEOMETRY_TOKEN_DIM,
    JunctionJointStoreInputs,
    audit_junction_joint_feature_rows,
    write_junction_joint_store,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_vector(
    path: Path,
    *,
    geometry_type: str,
    features: list[tuple[object, dict[str, object]]],
) -> None:
    properties: dict[str, str] = {}
    for _, row in features:
        for key, value in row.items():
            properties.setdefault(key, "int" if isinstance(value, int) else "str")
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer=path.stem,
        schema={"geometry": geometry_type, "properties": properties},
        crs="EPSG:3857",
    ) as sink:
        for geometry, row in features:
            sink.write(
                {"type": "Feature", "geometry": mapping(geometry), "properties": row}
            )


def _case_inputs(case_root: Path, *, case_id: str) -> None:
    case_root.mkdir()
    _write_vector(
        case_root / "nodes.gpkg",
        geometry_type="Point",
        features=[(Point(0, 0), {"id": int(case_id), "mainnodeid": int(case_id), "kind_2": 4})],
    )
    _write_vector(
        case_root / "roads.gpkg",
        geometry_type="LineString",
        features=[(LineString([(-20, 0), (20, 0)]), {"id": 1, "snodeid": 2, "enodeid": 3})],
    )
    _write_vector(
        case_root / "rcsdnode.gpkg",
        geometry_type="Point",
        features=[
            (Point(1, 0), {"id": 20, "mainnodeid": 20, "kind": 1}),
            (Point(-15, 1), {"id": 21, "mainnodeid": 20, "kind": 1}),
            (Point(15, 1), {"id": 22, "mainnodeid": 0, "kind": 1}),
        ],
    )
    _write_vector(
        case_root / "rcsdroad.gpkg",
        geometry_type="LineString",
        features=[(LineString([(-15, 1), (15, 1)]), {"id": 10, "snodeid": 21, "enodeid": 22})],
    )
    _write_vector(
        case_root / "drivezone.gpkg",
        geometry_type="Polygon",
        features=[(Polygon([(-8, -8), (8, -8), (8, 8), (-8, 8)]), {"id": 30})],
    )
    (case_root / "manifest.json").write_text("{}", encoding="utf-8")


def test_joint_store_physically_separates_features_labels_and_lineage(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "case"
    _case_inputs(case_root, case_id="100")
    surface = tmp_path / "surface.gpkg"
    _write_vector(
        surface,
        geometry_type="Polygon",
        features=[(Polygon([(-5, -5), (5, -5), (5, 5), (-5, 5)]), {"case_id": "100"})],
    )
    t05_nodes = tmp_path / "t05_nodes.gpkg"
    _write_vector(
        t05_nodes,
        geometry_type="Point",
        features=[(Point(1, 1), {"id": 20})],
    )
    hashes = [
        (name, sha256_file(case_root / name))
        for name in (
            "nodes.gpkg",
            "roads.gpkg",
            "rcsdnode.gpkg",
            "rcsdroad.gpkg",
            "drivezone.gpkg",
            "manifest.json",
        )
    ]
    legacy = tmp_path / "legacy"
    _write_jsonl(
        legacy / "inference_feature_store" / "anchor_features.jsonl",
        [
            {
                "sample_id": "old",
                "case_key": "T03:100",
                "object_features": [0.0] * 64,
                "candidate_ids": ["ROAD:10"],
                "candidate_features": [[0.0] * 64],
                "structural_member_ids": ["ROAD:10"],
                "swsd_arm_features": [],
                "member_arm_features": [[]],
                "member_local_features": [[0.0] * 12],
                "member_relation_edges": [],
                "input_hashes": hashes,
            }
        ],
    )
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [
            {
                "sample_id": "gold-100",
                "case_id": "100",
                "family": "T03",
                "source_scope": "POC_Data",
                "source_index": 1,
                "case_root": str(case_root),
                "input_fingerprint": "abc",
                "t07_step1_has_evd": "yes",
                "t07_step2_is_anchor": "",
                "route_class": "T03",
                "surface_state": "accepted",
                "surface_geometry_path": str(surface),
                "relation_state": "rcsd_present_not_junction",
                "anchor_business_state": "SUCCESS",
                "junctionization_action": "split_rcsdroad_generate_rcsdnode",
                "junctionization_action_gold_status": "READY",
                "complete_junction_gold_status": "READY",
                "t05_original_rcsdroad_ids": ["10"],
                "t05_new_rcsdnode_ids": ["20"],
                "t05_grouped_rcsdnode_ids": [],
                "t05_original_rcsdnode_ids": [],
                "selected_main_rcsdnode_id": "20",
                "t05_phase2_rcsdnode_path": str(t05_nodes),
                "terminal_business_signature": "sig",
            }
        ],
    )
    split = tmp_path / "split.jsonl"
    _write_jsonl(
        split,
        [
            {
                "sample_id": "gold-100",
                "case_id": "100",
                "source_index": 1,
                "split": "train",
                "effective_label_weight": 1.0,
            }
        ],
    )

    summary = write_junction_joint_store(
        inputs=JunctionJointStoreInputs(
            final_labels_path=labels,
            split_samples_path=split,
            legacy_feature_store_root=legacy,
        ),
        output_root=tmp_path / "out",
    )

    assert summary["status"] == "JUNCTION_JOINT_STORE_GO"
    assert summary["candidate_supervised_count"] == 1
    assert summary["member_supervised_count"] == 1
    assert summary["surface_grid_supervised_count"] == 1
    feature = json.loads(
        (tmp_path / "out/inference_feature_store/junction_features.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    label = json.loads(
        (tmp_path / "out/training_label_store/junction_labels.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    lineage = json.loads(
        (tmp_path / "out/lineage_store/junction_lineage.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    assert len(feature["geometry_token_features"][0]) == GEOMETRY_TOKEN_DIM
    assert feature["geometry_relation_edges"]
    assert all(
        len(edge[2]) == GEOMETRY_RELATION_DIM
        for edge in feature["geometry_relation_edges"]
    )
    assert "split" not in feature and "family" not in feature
    assert label["candidate_acceptable_indices"] == [0]
    assert label["task_labels"]["surface_mode"] == "VIRTUAL_SURFACE"
    assert label["task_masks"]["t07_step2"] is False
    assert label["topology_geometry_supervised"] is True
    assert lineage["family"] == "T03" and lineage["split"] == "train"


def test_feature_leakage_audit_rejects_terminal_fields() -> None:
    audit = audit_junction_joint_feature_rows(
        [{"sample_id": "a", "route_label": "T03", "object_features": [0.0]}]
    )
    assert audit["passed"] is False
    assert audit["violation_count"] == 1


def test_invalid_raw_geometry_is_encoded_without_repair(tmp_path: Path) -> None:
    case_root = tmp_path / "case"
    _case_inputs(case_root, case_id="100")
    invalid_drivezone = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    (case_root / "drivezone.gpkg").unlink()
    _write_vector(
        case_root / "drivezone.gpkg",
        geometry_type="Polygon",
        features=[(invalid_drivezone, {"id": 30})],
    )
    from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
        _geometry_evidence,
        _semantic_anchor_point,
    )

    evidence = _geometry_evidence(
        case_root,
        anchor_point=_semantic_anchor_point(case_root / "nodes.gpkg", "100"),
        radius_m=200.0,
    )
    drivezone_spans = [
        span for span in evidence["object_spans"] if span["role_index"] == 2
    ]
    assert drivezone_spans[0]["geometry_valid"] is False
    first = drivezone_spans[0]["token_start"]
    assert evidence["token_features"][first][15] == 0.0
