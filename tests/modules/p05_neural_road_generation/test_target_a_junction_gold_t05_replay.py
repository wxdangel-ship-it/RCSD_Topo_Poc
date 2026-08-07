from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import fiona
from shapely.geometry import Polygon, mapping, shape

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_gold_t05_replay import (
    JunctionGoldT05ReplayInputs,
    adapt_t03_surface_for_t05,
    adapt_t04_surface_for_t05,
    build_t03_relation_evidence,
    write_junction_gold_t05_replay,
)


def _write_surface(path: Path, *, case_id: str = "100") -> None:
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="surface",
        schema={"geometry": "Polygon", "properties": {"case_id": "str"}},
        crs="EPSG:3857",
    ) as sink:
        sink.write(
            {
                "type": "Feature",
                "geometry": mapping(Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])),
                "properties": {"case_id": case_id},
            }
        )


def _write_t03_surface(path: Path, *, case_id: str) -> None:
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="surface",
        schema={
            "geometry": "Polygon",
            "properties": {
                "case_id": "str",
                "template_class": "str",
                "step7_state": "str",
            },
        },
        crs="EPSG:3857",
    ) as sink:
        sink.write(
            {
                "type": "Feature",
                "geometry": mapping(Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])),
                "properties": {
                    "case_id": case_id,
                    "template_class": "single_sided_t_mouth",
                    "step7_state": "accepted",
                },
            }
        )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_t04_adapter_adds_formal_fields_without_geometry_change(tmp_path: Path) -> None:
    source = tmp_path / "source.gpkg"
    target = tmp_path / "target.gpkg"
    status = tmp_path / "status.json"
    _write_surface(source)
    _write_json(status, {"final_state": "accepted"})

    audit = adapt_t04_surface_for_t05(
        source_surface_path=source,
        step7_status_path=status,
        relation_row={
            "target_id": "100",
            "junction_type": "complex_divmerge",
            "patch_id": "900",
        },
        output_path=target,
    )

    assert audit["geometry_changed"] is False
    assert audit["silent_fix"] is False
    with fiona.open(source) as original, fiona.open(target) as adapted:
        original_feature = next(iter(original))
        adapted_feature = next(iter(adapted))
        assert shape(original_feature["geometry"]).equals_exact(
            shape(adapted_feature["geometry"]), 0.0
        )
        assert dict(adapted_feature["properties"])["final_state"] == "accepted"
        assert dict(adapted_feature["properties"])["mainnodeid"] == "100"
        assert dict(adapted_feature["properties"])["patch_id"] == "900"
        assert dict(adapted_feature["properties"])["kind_2"] == 128


def test_t03_adapter_adds_formal_kind_without_geometry_change(tmp_path: Path) -> None:
    source = tmp_path / "source.gpkg"
    target = tmp_path / "target.gpkg"
    with fiona.open(
        source,
        "w",
        driver="GPKG",
        layer="surface",
        schema={
            "geometry": "Polygon",
            "properties": {
                "case_id": "str",
                "template_class": "str",
                "step7_state": "str",
            },
        },
        crs="EPSG:3857",
    ) as sink:
        sink.write(
            {
                "type": "Feature",
                "geometry": mapping(Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])),
                "properties": {
                    "case_id": "100",
                    "template_class": "single_sided_t_mouth",
                    "step7_state": "accepted",
                },
            }
        )

    audit = adapt_t03_surface_for_t05(
        source_surface_path=source,
        case_id="100",
        output_path=target,
    )

    assert audit["geometry_changed"] is False
    with fiona.open(target) as adapted:
        properties = dict(next(iter(adapted))["properties"])
        assert properties["mainnodeid"] == "100"
        assert properties["kind_2"] == 2048


def test_t03_relation_evidence_preserves_road_only_support() -> None:
    row = build_t03_relation_evidence(
        {
            "case_id": "200",
            "relation_state": "rcsd_present_not_junction",
            "anchor_business_state": "SUCCESS",
            "selected_rcsd_node_ids": [],
            "selected_rcsd_road_ids": [],
            "support_rcsd_road_ids": ["7", "8"],
        }
    )
    assert row["status_suggested"] == 0
    assert row["base_id_candidate"] == ""
    assert row["support_rcsdroad_ids"] == "7|8"


def test_full_replay_writes_success_ledger_with_mocked_t05(
    tmp_path: Path, monkeypatch
) -> None:
    case_root = tmp_path / "case"
    case_root.mkdir()
    for name in ("nodes.gpkg", "rcsdroad.gpkg", "rcsdnode.gpkg"):
        (case_root / name).write_bytes(b"placeholder")
    source = tmp_path / "surface.gpkg"
    _write_t03_surface(source, case_id="200")
    labels = tmp_path / "labels.jsonl"
    label = {
        "sample_id": "sample-200",
        "sample_group_id": "junction:200",
        "case_id": "200",
        "family": "T03",
        "source_scope": "POC_Data",
        "input_fingerprint": "abc",
        "label_status": "READY",
        "surface_state": "accepted",
        "surface_geometry_path": str(source),
        "case_root": str(case_root),
        "relation_state": "rcsd_present_not_junction",
        "anchor_business_state": "SUCCESS",
        "selected_rcsd_node_ids": [],
        "selected_rcsd_road_ids": [],
        "support_rcsd_road_ids": ["7"],
        "replay_status_path": "",
    }
    labels.write_text(json.dumps(label) + "\n", encoding="utf-8")
    empty_relation = tmp_path / "t04.json"
    _write_json(empty_relation, {"rows": []})

    phase1_root = tmp_path / "mock_phase1"
    phase1_root.mkdir()
    phase1_surface = phase1_root / "surface.gpkg"
    _write_surface(phase1_surface, case_id="200")
    phase1_audit = phase1_root / "audit.json"
    _write_json(phase1_audit, {"rows": []})
    phase2_root = tmp_path / "mock_phase2"
    phase2_root.mkdir()
    phase2_audit = phase2_root / "audit.json"
    phase2_summary = phase2_root / "summary.json"
    _write_json(phase2_summary, {"passed": True})
    _write_json(
        phase2_audit,
        {
            "rows": [
                {
                    "scene": "road_only_split",
                    "action": "split_rcsdroad_generate_rcsdnode",
                    "reason": "t03_b2_road_only_support",
                    "selected_main_rcsdnode_id": "11",
                    "original_rcsdroad_ids": "7",
                    "new_rcsdroad_ids": "70|71",
                    "new_rcsdnode_ids": "11",
                    "blocking_error": 0,
                }
            ]
        },
    )
    for name in ("relation.geojson", "road.gpkg", "node.gpkg"):
        (phase2_root / name).write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_gold_t05_replay._run_phase1",
        lambda **_: SimpleNamespace(
            published_surface_count=1,
            conflict_count=0,
            skipped_count=0,
            surface_path=phase1_surface,
            audit_json_path=phase1_audit,
        ),
    )
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_gold_t05_replay._run_phase2",
        lambda **_: SimpleNamespace(
            relation_count=1,
            success_count=1,
            failure_count=0,
            rcsd_junctionization_audit_json_path=phase2_audit,
            summary_path=phase2_summary,
            relation_geojson_path=phase2_root / "relation.geojson",
            rcsdroad_out_path=phase2_root / "road.gpkg",
            rcsdnode_out_path=phase2_root / "node.gpkg",
        ),
    )

    summary = write_junction_gold_t05_replay(
        inputs=JunctionGoldT05ReplayInputs(
            labels_path=labels,
            poc_data_t04_relation_path=empty_relation,
            poc_data_t04_error_relation_path=empty_relation,
        ),
        output_root=tmp_path / "out",
        workers=2,
    )

    assert summary["status"] == "JUNCTION_GOLD_T05_REPLAY_GO"
    assert summary["accepted_surface_count"] == 1
    assert summary["phase2_success_count"] == 1
    ledger = json.loads(
        (tmp_path / "out" / "junction_gold_t05_replay.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    assert ledger["status"] == "SUCCESS"
    assert ledger["scene"] == "road_only_split"
    assert ledger["topology_changed"] is True
