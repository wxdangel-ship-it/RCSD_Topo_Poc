from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_dataset_p0 import (
    _artifact_contract,
    _candidate_source_category,
    _decision,
    _expected_weight_pair,
    _gpkg_object_ids,
    _module_role_contract,
    _normalized_id,
    _peak_rss_bytes,
    _validate_candidate_summary,
    _verify_declared_file,
    _verify_sample_manifest,
    compare_scheme_a_dataset_p0_runs,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_dataset_p0_models import (
    SchemeADatasetP0Config,
)


def _config(tmp_path: Path, **overrides: object) -> SchemeADatasetP0Config:
    values: dict[str, object] = {
        "m0_run_root": tmp_path / "m0",
        "m2r_supervision_run_root": tmp_path / "m2r",
        "scheme_a_baseline_run_root": tmp_path / "baseline",
        "pto_candidate_run_root": tmp_path / "candidate",
        "pto_solve_run_root": tmp_path / "solve",
        "historical_p2_oracle_run_root": tmp_path / "p2",
        "poc_data_root": Path(r"E:\TestData\POC_Data"),
        "output_root": tmp_path / "out",
        "run_id": "dataset-p0-test",
    }
    values.update(overrides)
    return SchemeADatasetP0Config(**values)  # type: ignore[arg-type]


def test_config_freezes_t07_drivezone_only(tmp_path: Path) -> None:
    assert _config(tmp_path).t07_evidence_mode == "DRIVEZONE_ONLY"
    with pytest.raises(ValueError, match="DriveZone-only"):
        _config(tmp_path, t07_evidence_mode="DRIVEZONE_UNION_RCSDINTERSECTION")


def test_module_roles_keep_t01_out_of_rcsd_truth() -> None:
    roles = {row["module"]: row for row in _module_role_contract()}
    assert set(roles) == {"T01", "T07", "T03", "T04", "T05", "T06", "T09", "T11", "T10"}
    assert roles["T01"]["training_role"] == "INPUT_FROZEN_SKELETON"
    assert roles["T01"]["label_only"] is False
    assert roles["T07"]["evidence_mode"] == "DRIVEZONE_ONLY"
    assert roles["T11"]["candidate_role"] == "ACTIVE_LEARNING_ONLY"
    assert roles["T09"]["training_role"] == "DOWNSTREAM_VALIDATION_ONLY"


def test_artifact_and_weight_contracts_are_explicit() -> None:
    assert _artifact_contract("t01_segment") == (
        "T01",
        "INPUT_FROZEN_SKELETON",
        True,
        False,
    )
    assert _artifact_contract("t06_frcsd_road")[1:] == (
        "LABEL_ONLY_PRIMARY_TARGET",
        False,
        True,
    )
    with pytest.raises(ValueError, match="unknown M0 artifact role"):
        _artifact_contract("t11_machine_candidate_as_truth")
    assert _expected_weight_pair("T03_Error") == (1.0, 0.3)
    assert _expected_weight_pair("T04") == (1.0, 0.3)
    assert _expected_weight_pair("T10") == (0.7, 0.7)
    assert _expected_weight_pair("T10-Error") == (0.7, 0.3)


def test_candidate_source_separates_t01_fallback_from_rcsd_proposal() -> None:
    assert _candidate_source_category(
        [{"role": "t01_roads", "source_kind": "BASE_IDENTITY"}]
    ) == {"T01_OR_SWSD_FALLBACK"}
    assert _candidate_source_category(
        [{"role": "rcsdroad", "source_kind": "BASE_IDENTITY"}]
    ) == {"NON_T01_PROPOSAL"}
    assert _candidate_source_category(
        [{"role": "t06_frcsd_road", "source_kind": "STRATEGY_REPLAY"}]
    ) == {"NON_T01_PROPOSAL"}
    assert _candidate_source_category(
        [
            {"role": "t01_roads", "source_kind": "BASE_IDENTITY"},
            {"role": "t06_frcsd_road", "source_kind": "STRATEGY_REPLAY"},
        ]
    ) == {"T01_OR_SWSD_FALLBACK", "NON_T01_PROPOSAL"}


def test_candidate_summary_rejects_truth_leakage() -> None:
    valid = {
        "case_count": 51,
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "unbounded_enumeration": False,
    }
    _validate_candidate_summary(valid, 51)
    with pytest.raises(ValueError, match="truth input"):
        _validate_candidate_summary({**valid, "truth_input_count": 1}, 51)
    with pytest.raises(ValueError, match="truth-derived"):
        _validate_candidate_summary({**valid, "truth_derived_candidate_count": 1}, 51)


def test_id_and_hash_validation_do_not_silent_fix(tmp_path: Path) -> None:
    assert _normalized_id("123.0") == "123"
    assert _normalized_id("123.5") == "123.5"
    assert _normalized_id(None) == ""
    target = tmp_path / "evidence.bin"
    target.write_bytes(b"evidence")
    passed, status = _verify_declared_file(target, "0" * 64, strict=True)
    assert passed is False
    assert status == "hash_mismatch"


def test_t10_organization_fallback_uses_stable_record_hash(tmp_path: Path) -> None:
    organization = tmp_path / "_t10_case_organization_manifest.json"
    organization.write_text('{"unrelated":"file-level content"}', encoding="utf-8")
    record = {"case_id": "1885118", "action": "renamed_to_case_id_directory"}
    expected = __import__("hashlib").sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    passed, status = _verify_sample_manifest(
        {
            "manifest_path": str(organization),
            "manifest_sha256": expected,
            "source_metadata": json.dumps(
                {
                    "package_type": "t10_case_organization_fallback",
                    "organization_record": record,
                }
            ),
        },
        strict=True,
    )
    assert passed is True
    assert status == "ok"


def test_gpkg_reader_checks_ids_crs_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "nodes.gpkg"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER);
        CREATE TABLE gpkg_spatial_ref_sys (
          srs_name TEXT, srs_id INTEGER, organization TEXT,
          organization_coordsys_id INTEGER, definition TEXT, description TEXT
        );
        CREATE TABLE nodes (fid INTEGER PRIMARY KEY, id TEXT);
        INSERT INTO gpkg_contents VALUES ('nodes', 'features', 3857);
        INSERT INTO gpkg_spatial_ref_sys VALUES ('WGS 84 / Pseudo-Mercator', 3857, 'EPSG', 3857, '', '');
        INSERT INTO nodes(id) VALUES ('1'), ('1.0'), ('2');
        """
    )
    connection.commit()
    connection.close()
    ids, crs_values, duplicate_count = _gpkg_object_ids(path)
    assert ids == {"1", "2"}
    assert crs_values == {"EPSG:3857"}
    assert duplicate_count == 1


def test_decision_distinguishes_label_candidate_and_safety_failures() -> None:
    assert _decision(True, True, True, True, True) == "P05_SCHEME_A_DATASET_P0_GO"
    assert _decision(False, True, True, True, True).endswith("LABEL_NO_GO")
    assert _decision(True, True, False, True, True).endswith("CANDIDATE_NO_GO")
    assert _decision(True, True, True, False, True).endswith("SAFETY_NO_GO")


def test_resource_audit_reports_nonzero_process_memory() -> None:
    assert _peak_rss_bytes() > 0


def test_compare_runs_ignores_runtime_only_values(tmp_path: Path) -> None:
    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    run_a.mkdir()
    run_b.mkdir()
    base = {
        "decision": "P05_SCHEME_A_DATASET_P0_GO",
        "gates": {"gate0": True},
        "signatures": {"sample": "same", "candidate": "same"},
    }
    (run_a / "dataset_p0_summary.json").write_text(
        json.dumps({**base, "performance": {"wall_seconds": 1.0}}), encoding="utf-8"
    )
    (run_b / "dataset_p0_summary.json").write_text(
        json.dumps({**base, "performance": {"wall_seconds": 2.0}}), encoding="utf-8"
    )
    output = tmp_path / "determinism.json"
    result = compare_scheme_a_dataset_p0_runs(run_a, run_b, output_path=output)
    assert result["determinism_pass"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["signatures_equal"] is True
