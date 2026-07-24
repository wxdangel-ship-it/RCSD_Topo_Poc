from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    finalize_segment_first_run,
)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _acceptance_bundle(root: Path, *, overlay_pass: bool = True) -> Path:
    for name in (
        "p04_segment_first_rcsd.gpkg",
        "p04_segment_first_audit.gpkg",
        "p04_segment_first_relations.gpkg",
        "p04_segment_first_independent_quality.json",
        "p04_segment_first_comparison.qgz",
    ):
        (root / name).write_bytes(name.encode("utf-8"))
    _write(
        root / "p04_segment_first_summary.json",
        {
            "run_id": "run-a",
            "terminal_status": "technical_passed",
            "core_gate_pass": True,
            "independent_quality": {"gate_pass": True},
            "qgis": {"readback_pass": True},
        },
    )
    (root / "p04_segment_first_report.md").write_text(
        "# report\n\n- 终态：`technical_passed`\n",
        encoding="utf-8",
    )
    (root / "manual.png").write_bytes(b"png")
    _write(
        root / "overlay.json",
        {
            "gate_pass": overlay_pass,
            "selected_layers": ["new_built_roads"],
        },
    )
    _write(
        root / "pyqgis.json",
        {
            "project_read": True,
            "invalid_layer_count": 0,
            "spatial_renderer_missing_count": 0,
        },
    )
    _write(
        root / "determinism.json",
        {
            "gate_pass": True,
            "formal_layers_compared": ["Road", "Node", "RoadNextRoad"],
        },
    )
    _write(
        root / "manual.json",
        {
            "decision": "accepted_with_review",
            "hard_failure_count": 0,
            "review_required_count": 2,
            "reviewed_case_count": 4,
            "audit_image": "manual.png",
        },
    )
    manifest = root / "acceptance_manifest.json"
    _write(
        manifest,
        {
            "run_id": "run-a",
            "qgis_overlay_report": "overlay.json",
            "pyqgis_readback_report": "pyqgis.json",
            "determinism_report": "determinism.json",
            "manual_audit_report": "manual.json",
        },
    )
    return manifest


def test_finalizer_promotes_only_complete_acceptance_bundle(tmp_path: Path) -> None:
    manifest = _acceptance_bundle(tmp_path)
    result = finalize_segment_first_run(tmp_path, manifest)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    report = result.report_path.read_text(encoding="utf-8")

    assert result.terminal_status == "passed"
    assert summary["terminal_status"] == "passed"
    assert summary["acceptance"]["manual_decision"] == "accepted_with_review"
    assert "- 终态：`passed`" in report
    assert (tmp_path / "p04_segment_first_acceptance.json").is_file()


def test_finalizer_rejects_failed_external_gate(tmp_path: Path) -> None:
    manifest = _acceptance_bundle(tmp_path, overlay_pass=False)

    with pytest.raises(ValueError, match="overlay gate"):
        finalize_segment_first_run(tmp_path, manifest)

    summary = json.loads(
        (tmp_path / "p04_segment_first_summary.json").read_text(encoding="utf-8")
    )
    assert summary["terminal_status"] == "technical_passed"
