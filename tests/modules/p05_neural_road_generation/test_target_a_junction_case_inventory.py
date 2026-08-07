from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_case_inventory import (
    JunctionGoldRoot,
    scan_junction_gold_inventory,
    write_junction_gold_inventory,
)


def test_inventory_deduplicates_identical_case_sources(tmp_path: Path) -> None:
    first = tmp_path / "POC_Data" / "T03"
    second = tmp_path / "POC_QA" / "T03_Error"
    _case(first / "100", "100", payload=b"same")
    _case(second / "100", "100", payload=b"same")

    sources, cases, anomalies, summary = scan_junction_gold_inventory(
        (
            JunctionGoldRoot(first, "T03", "POC_Data"),
            JunctionGoldRoot(second, "T03_Error", "POC_QA"),
        ),
        verify_vector_crs=False,
    )

    assert len(sources) == 2
    assert len(cases) == 1
    assert cases[0].status == "READY"
    assert cases[0].exact_duplicate_count == 1
    assert cases[0].families == ("T03", "T03_Error")
    assert anomalies == ()
    assert summary["unique_case_id_count"] == 1


def test_inventory_quarantines_same_case_with_different_raw_inputs(
    tmp_path: Path,
) -> None:
    first = tmp_path / "POC_Data" / "T03"
    second = tmp_path / "POC_Data" / "T03_Error"
    _case(first / "100", "100", payload=b"first")
    _case(second / "100", "100", payload=b"second")

    _, cases, anomalies, summary = scan_junction_gold_inventory(
        (
            JunctionGoldRoot(first, "T03", "POC_Data"),
            JunctionGoldRoot(second, "T03_Error", "POC_Data"),
        ),
        verify_vector_crs=False,
    )

    assert cases[0].status == "LABEL_REVIEW"
    assert cases[0].selected_case_root is None
    assert cases[0].distinct_input_version_count == 2
    assert any(row.category == "source_version_conflict" for row in anomalies)
    assert summary["status"] == "JUNCTION_GOLD_INVENTORY_REVIEW"


def test_inventory_rejects_checksum_mismatch_without_silent_fix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "POC_Data" / "T04"
    case_root = _case(root / "200", "200", payload=b"before")
    (case_root / "nodes.gpkg").write_bytes(b"after")

    sources, cases, anomalies, _ = scan_junction_gold_inventory(
        (JunctionGoldRoot(root, "T04", "POC_Data"),),
        verify_vector_crs=False,
    )

    assert sources[0].status == "SOURCE_INVALID"
    assert cases[0].status == "SOURCE_INVALID"
    assert any(row.category == "checksum_mismatch:nodes.gpkg" for row in anomalies)


def test_inventory_uses_current_hash_after_declared_predecode_bundle_hash(
    tmp_path: Path,
) -> None:
    root = tmp_path / "POC_QA" / "T03_Error"
    case_root = _case(root / "250", "250", payload=b"localized")
    manifest_path = case_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["decoded_output"] = {
        "vector_coordinates": "absolute_epsg3857",
        "vector_crs": "EPSG:3857",
        "bundle_internal_vectors_localized": True,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (case_root / "nodes.gpkg").write_bytes(b"decoded-absolute-coordinates")

    sources, cases, anomalies, _ = scan_junction_gold_inventory(
        (JunctionGoldRoot(root, "T03_Error", "POC_QA"),),
        verify_vector_crs=False,
    )

    assert sources[0].status == "READY"
    assert cases[0].status == "READY"
    assert anomalies == ()


def test_inventory_artifacts_are_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "POC_Data" / "T03_Error"
    _case(root / "300", "300", payload=b"stable")
    spec = (JunctionGoldRoot(root, "T03_Error", "POC_Data"),)

    first = write_junction_gold_inventory(
        output_root=tmp_path / "run-a",
        roots=spec,
        verify_vector_crs=False,
    )
    second = write_junction_gold_inventory(
        output_root=tmp_path / "run-b",
        roots=spec,
        verify_vector_crs=False,
    )

    for role in ("sources", "cases", "anomalies"):
        assert first["artifacts"][role]["sha256"] == second["artifacts"][role]["sha256"]
    assert first["silent_fix"] is False


def _case(case_root: Path, case_id: str, *, payload: bytes) -> Path:
    case_root.mkdir(parents=True)
    checksums: dict[str, str] = {}
    for name in (
        "nodes.gpkg",
        "roads.gpkg",
        "rcsdnode.gpkg",
        "rcsdroad.gpkg",
        "drivezone.gpkg",
    ):
        content = payload + b":" + name.encode("ascii")
        (case_root / name).write_bytes(content)
        checksums[name] = hashlib.sha256(content).hexdigest()
    (case_root / "manifest.json").write_text(
        json.dumps(
            {
                "bundle_version": "1",
                "bundle_mode": "single_case",
                "mainnodeid": case_id,
                "epsg": 3857,
                "checksum": checksums,
            }
        ),
        encoding="utf-8",
    )
    return case_root
