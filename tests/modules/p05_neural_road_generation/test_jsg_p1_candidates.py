from pathlib import Path
import json

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation import jsg_p1_candidates as subject


def _case() -> subject.P1EvidenceCase:
    return subject.P1EvidenceCase(
        sample_id="sample",
        family="T10",
        business_id="fixture",
        t01_segment=Path("segment.gpkg"),
        t01_nodes=Path("nodes.gpkg"),
        t01_roads=Path("roads.gpkg"),
        source_manifest=Path("manifest.json"),
        source_hashes=(
            ("pto_candidate_manifest", "m"),
            ("t01_segment", "s"),
            ("t01_nodes", "n"),
            ("t01_roads", "r"),
        ),
        roadgraph_candidate_count=7,
        roadgraph_candidate_signature="roadgraph-signature",
        replay_duration_seconds=1.0,
        candidate_build_seconds=0.5,
    )


def test_candidate_builder_enumerates_semantic_and_carrier_domains(monkeypatch) -> None:
    segment_rows = [
        {"id": "s1", "pair_nodes": ["j1", "j2"], "junc_nodes": [], "roads": ["r1"], "sgrade": "1"},
        {"id": "s2", "pair_nodes": ["j2", "j3"], "junc_nodes": [], "roads": ["r2"], "sgrade": "1"},
        {"id": "c1", "pair_nodes": ["j1", "j3"], "junc_nodes": [], "roads": ["r3"], "segment_type": "advance_right"},
    ]
    monkeypatch.setattr(
        subject,
        "_read_properties",
        lambda path: (segment_rows, "EPSG:3857") if path.name == "segment.gpkg" else ([], "EPSG:3857"),
    )
    monkeypatch.setattr(
        subject,
        "read_vector_payloads",
        lambda *_args, **_kwargs: ({}, {"crs_wkt": "EPSG:3857"}),
    )
    monkeypatch.setattr(subject, "_semantic_node_index", lambda _rows: ({}, {}))
    monkeypatch.setattr(subject, "_node_semantics", lambda *_args: (set(), set()))
    monkeypatch.setattr(subject, "_terminal_evidence", lambda *_args: ({}, {}))

    candidates, summary = subject.build_p1_case_candidates(_case())
    groups = {row.group_id for row in candidates}

    assert summary["standard_segment_count"] == 2
    assert summary["movement_group_count"] == 2
    assert summary["connector_group_count"] == 1
    assert "PTO_A:PHYSICAL_MOVEMENT:j2:s1->s2" in groups
    assert "PTO_A:PHYSICAL_MOVEMENT:j2:s2->s1" in groups
    assert "PTO_A:SEGMENT_CONNECTOR:c1" in groups
    assert sum(row.stage.value == "PTO_B" for row in candidates) == 1
    assert all(not row.truth_derived and not row.label_only for row in candidates)
    assert all(row.source_kinds for row in candidates)


def test_candidate_builder_rejects_crs_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "_read_properties",
        lambda path: ([], "EPSG:3857") if path.name == "segment.gpkg" else ([], "EPSG:4326"),
    )
    monkeypatch.setattr(
        subject,
        "read_vector_payloads",
        lambda *_args, **_kwargs: ({}, {"crs_wkt": "EPSG:3857"}),
    )

    try:
        subject.build_p1_case_candidates(_case())
    except ValueError as error:
        assert "CRS mismatch" in str(error)
    else:
        raise AssertionError("CRS mismatch was accepted")


def test_candidate_loader_rejects_upstream_truth_declaration(tmp_path) -> None:
    run_root = tmp_path / "candidate"
    run_root.mkdir()
    (run_root / "p05_pto_candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "p05-pto-candidate-manifest-v1",
                "status": "candidate_scope_passed",
                "silent_fix": False,
                "truth_input_count": 1,
                "truth_derived_candidate_count": 0,
            }
        ),
        encoding="utf-8",
    )
    config = subject.JSGP1CandidateConfig(
        pto_candidate_run_root=run_root,
        output_root=tmp_path,
        run_id="probe",
        poc_data_root=tmp_path,
        strict_hashes=False,
        enforce_poc_scope=False,
    )

    with pytest.raises(ValueError, match="truth input"):
        subject.load_p1_evidence_cases(config)
