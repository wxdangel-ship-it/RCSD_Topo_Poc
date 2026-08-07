from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import Point, mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_gold_labels import (
    JunctionGoldReplayRoots,
    build_junction_gold_labels,
)


def test_t03_label_keeps_surface_and_anchor_relation_separate(tmp_path: Path) -> None:
    case_root = _source_case(tmp_path / "source" / "100", "100")
    inventory = _inventory(tmp_path, case_root, family="T03", fingerprint="a" * 64)
    roots = _replay_roots(tmp_path)
    case_dir = roots.poc_data_t03 / "cases" / "100"
    _t03_replay(case_dir, accepted=True, association_class="B")

    labels, reviews, summary = build_junction_gold_labels(
        inventory_sources_path=inventory,
        replay_roots=roots,
    )

    assert len(labels) == 1
    assert labels[0].surface_state == "accepted"
    assert labels[0].relation_state == "rcsd_present_not_junction"
    assert labels[0].anchor_business_state == "QUALITY_ISSUE"
    assert labels[0].t07_step1_has_evd == "yes"
    assert labels[0].t07_step2_is_anchor == ""
    assert labels[0].t07_step2_input_terminal_value == "no"
    assert labels[0].t07_step2_gold_status == "MASKED_TERMINAL_ONLY"
    assert reviews == ()
    assert summary["status"] == "JUNCTION_GOLD_LABELS_GO"


def test_t04_runtime_failure_is_quality_issue_not_no_evidence(tmp_path: Path) -> None:
    case_root = _source_case(tmp_path / "source" / "200", "200")
    inventory = _inventory(
        tmp_path,
        case_root,
        family="T04_Error",
        fingerprint="b" * 64,
    )
    roots = _replay_roots(tmp_path)
    _relation_file(roots.poc_data_t04, [])
    _relation_file(roots.poc_data_t04_error, [])
    failure = roots.poc_data_t04_error / "failures" / "200.failure.json"
    failure.parent.mkdir(parents=True)
    failure.write_text(
        json.dumps(
            {
                "case_id": "200",
                "exception_type": "Stage4RunError",
                "message": "unsupported kind",
            }
        ),
        encoding="utf-8",
    )

    labels, _, _ = build_junction_gold_labels(
        inventory_sources_path=inventory,
        replay_roots=roots,
    )

    assert labels[0].surface_state == "runtime_failed"
    assert labels[0].relation_state == "runtime_failed"
    assert labels[0].anchor_business_state == "QUALITY_ISSUE"
    assert labels[0].replay_exception_type == "Stage4RunError"


def test_different_inputs_with_same_terminal_truth_are_reported(tmp_path: Path) -> None:
    first = _source_case(tmp_path / "first" / "300", "300")
    second = _source_case(tmp_path / "second" / "300", "300")
    inventory = tmp_path / "sources.jsonl"
    rows = [
        _source_row(0, first, "T03", "a" * 64),
        _source_row(1, second, "T03", "b" * 64),
    ]
    inventory.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    roots = _replay_roots(tmp_path)
    _t03_replay(
        roots.poc_data_t03 / "cases" / "300",
        accepted=False,
        association_class="C",
    )

    _, reviews, summary = build_junction_gold_labels(
        inventory_sources_path=inventory,
        replay_roots=roots,
    )

    assert reviews[0].source_version_count == 2
    assert reviews[0].status == "SAME_TERMINAL_BUSINESS"
    assert summary["source_version_same_terminal_count"] == 1


def _replay_roots(tmp_path: Path) -> JunctionGoldReplayRoots:
    roots = JunctionGoldReplayRoots(
        poc_data_t03=tmp_path / "replay" / "t03",
        poc_data_t03_explicit_excluded=tmp_path / "replay" / "t03-extra",
        poc_data_t03_error=tmp_path / "replay" / "t03-error",
        poc_qa_t03_error=tmp_path / "replay" / "qa-t03-error",
        poc_data_t04=tmp_path / "replay" / "t04",
        poc_data_t04_error=tmp_path / "replay" / "t04-error",
    )
    _relation_file(roots.poc_data_t04, [])
    _relation_file(roots.poc_data_t04_error, [])
    return roots


def _source_case(case_root: Path, case_id: str) -> Path:
    case_root.mkdir(parents=True)
    schema = {
        "geometry": "Point",
        "properties": {
            "id": "str",
            "has_evd": "str",
            "is_anchor": "str",
        },
    }
    with fiona.open(
        case_root / "nodes.gpkg",
        "w",
        driver="GPKG",
        layer="nodes",
        schema=schema,
        crs="EPSG:3857",
    ) as sink:
        sink.write(
            {
                "geometry": mapping(Point(0, 0)),
                "properties": {
                    "id": case_id,
                    "has_evd": "yes",
                    "is_anchor": "no",
                },
            }
        )
    return case_root


def _inventory(
    tmp_path: Path,
    case_root: Path,
    *,
    family: str,
    fingerprint: str,
) -> Path:
    path = tmp_path / "sources.jsonl"
    path.write_text(
        json.dumps(_source_row(0, case_root, family, fingerprint)) + "\n",
        encoding="utf-8",
    )
    return path


def _source_row(
    index: int,
    case_root: Path,
    family: str,
    fingerprint: str,
) -> dict[str, object]:
    return {
        "source_index": index,
        "case_id": case_root.name,
        "family": family,
        "source_scope": "POC_Data",
        "case_root": str(case_root),
        "input_fingerprint": fingerprint,
        "label_weight": 1.0,
        "status": "READY",
    }


def _t03_replay(
    case_dir: Path,
    *,
    accepted: bool,
    association_class: str,
) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "step7_status.json").write_text(
        json.dumps(
            {
                "step7_state": "accepted" if accepted else "rejected",
                "association_class": association_class,
                "reason": "test",
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "step6_audit.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "required_rcsdnode_ids": [],
                    "required_rcsdroad_ids": [],
                    "support_rcsdnode_ids": [],
                    "support_rcsdroad_ids": [],
                }
            }
        ),
        encoding="utf-8",
    )
    if accepted:
        _polygon_file(case_dir / "step7_final_polygon.gpkg")


def _polygon_file(path: Path) -> None:
    schema = {"geometry": "Polygon", "properties": {"id": "str"}}
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="surface",
        schema=schema,
        crs="EPSG:3857",
    ) as sink:
        sink.write(
            {
                "geometry": mapping(Point(0, 0).buffer(5)),
                "properties": {"id": "surface"},
            }
        )


def _relation_file(root: Path, rows: list[dict[str, object]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "t04_swsd_rcsd_relation_evidence.json").write_text(
        json.dumps({"rows": rows}),
        encoding="utf-8",
    )
