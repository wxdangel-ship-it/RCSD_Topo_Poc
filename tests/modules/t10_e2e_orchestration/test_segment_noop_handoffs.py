from __future__ import annotations

from pathlib import Path

import fiona

from rcsd_topo_poc.modules.t10_e2e_orchestration.segment_noop_handoffs import (
    try_segment_no_candidate_handoff,
)


def test_segment_t07_no_intersection_handoff_writes_explicit_outputs(tmp_path: Path) -> None:
    source_nodes = tmp_path / "t01_nodes.gpkg"
    _write_node_fixture(source_nodes)
    record = {
        "status": "failed",
        "stdout_tail": ["T07RunError: RCSDIntersection layer has no non-empty geometry."],
    }

    produced = try_segment_no_candidate_handoff(
        "t07",
        "segment_520649671_605650271",
        tmp_path / "t07_stage",
        record,
        {"t01_nodes": source_nodes},
        {"t07_nodes": "", "t07_surface": "", "t07_relation_evidence": ""},
    )

    assert produced is not None
    assert record["status"] == "passed"
    assert Path(produced["t07_relation_evidence"]).read_text(encoding="utf-8").startswith("target_id,representative_node_id")
    with fiona.open(produced["t07_nodes"]) as src:
        assert len(src) == 1
        row = next(iter(src))
        assert row["properties"]["has_evd"] == "no"
        assert row["properties"]["is_anchor"] == "no"
    with fiona.open(produced["t07_surface"]) as src:
        assert len(src) == 0


def test_segment_t03_no_candidate_handoff_writes_explicit_outputs(tmp_path: Path) -> None:
    source_nodes = tmp_path / "t07_nodes.gpkg"
    source_nodes.write_bytes(b"placeholder nodes")
    record = {
        "status": "failed",
        "stdout_tail": ["ValueError: No eligible T03 internal full-input cases were discovered"],
    }

    produced = try_segment_no_candidate_handoff(
        "t03",
        "segment_1537607_512643052",
        tmp_path / "t03_stage",
        record,
        {"t07_nodes": source_nodes},
        {"t03_nodes": "", "t03_surface": "", "t03_relation_evidence": "", "t03_intersection_match": ""},
    )

    assert produced is not None
    assert record["status"] == "passed"
    assert record["segment_no_candidate_handoff"] is True
    assert Path(produced["t03_nodes"]).read_bytes() == b"placeholder nodes"
    assert Path(produced["t03_relation_evidence"]).read_text(encoding="utf-8").startswith("target_id,case_id")
    with fiona.open(produced["t03_surface"]) as src:
        assert len(src) == 0


def test_segment_t04_no_candidate_handoff_writes_explicit_outputs(tmp_path: Path) -> None:
    source_nodes = tmp_path / "t03_nodes.gpkg"
    source_nodes.write_bytes(b"placeholder nodes")
    record = {
        "status": "failed",
        "stdout_tail": ["ValueError: No eligible T04 candidates were discovered."],
    }

    produced = try_segment_no_candidate_handoff(
        "t04",
        "segment_924076_14313744",
        tmp_path / "t04_stage",
        record,
        {"t03_nodes": source_nodes},
        {
            "final_swsd_nodes": "",
            "t04_nodes": "",
            "t04_surface": "",
            "t04_relation_evidence": "",
            "t04_summary": "",
            "t04_audit": "",
        },
    )

    assert produced is not None
    assert record["status"] == "passed"
    assert Path(produced["final_swsd_nodes"]).read_bytes() == b"placeholder nodes"
    assert Path(produced["t04_summary"]).read_text(encoding="utf-8").startswith("case_id,anchor_id")
    with fiona.open(produced["t04_surface"]) as src:
        assert len(src) == 0


def test_no_candidate_handoff_is_segment_only(tmp_path: Path) -> None:
    record = {
        "status": "failed",
        "stdout_tail": ["ValueError: No eligible T04 candidates were discovered."],
    }

    produced = try_segment_no_candidate_handoff(
        "t04",
        "1885118",
        tmp_path / "t04_stage",
        record,
        {"t03_nodes": tmp_path / "missing.gpkg"},
        {"t04_nodes": ""},
    )

    assert produced is None
    assert record["status"] == "failed"


def _write_node_fixture(path: Path) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "kind_2": "str"}}
    with fiona.open(
        path,
        mode="w",
        driver="GPKG",
        layer=path.stem,
        schema=schema,
        crs="EPSG:3857",
        encoding="utf-8",
    ) as dst:
        dst.write({"geometry": {"type": "Point", "coordinates": (0.0, 0.0)}, "properties": {"id": "n1", "kind_2": "4"}})
