from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rcsd_topo_poc.modules.t10_e2e_orchestration import case_runner as t10_case_runner
from rcsd_topo_poc.modules.t11_manual_relation_review.extract_pipeline import _discover_inputs


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_t11_is_between_t06_and_t09_in_case_runner() -> None:
    order = t10_case_runner.T10_E2E_STAGE_ORDER
    assert order[order.index("t06_step3") + 1] == "t11"
    assert order[order.index("t11") + 1] == "t09_step12"
    assert t10_case_runner.T10_E2E_STAGE_MODULES["t11"] == "t11_manual_relation_review"


def test_t11_case_stage_invokes_existing_entry_and_publishes_outputs(tmp_path: Path, monkeypatch) -> None:
    case_run_dir = tmp_path / "cases" / "1885118"
    case_run_dir.mkdir(parents=True)
    stage_dir = case_run_dir / "t11"
    handoffs = {
        "t06_step3_summary": str(_touch(tmp_path / "t06" / "summary.json")),
        "t06_frcsd_road": str(_touch(tmp_path / "t06" / "road.gpkg")),
        "t06_frcsd_node": str(_touch(tmp_path / "t06" / "node.gpkg")),
        "t06_swsd_frcsd_segment_relation": str(_touch(tmp_path / "t06" / "relation.gpkg")),
    }
    captured = {}

    def fake_execute(stage_id, target_dir, repo_root, command, env_overrides, inputs):
        captured.update(stage_id=stage_id, command=command, inputs=inputs)
        run_root = target_dir / "run_test"
        _touch(run_root / "t11_relation_repair_candidates.csv")
        _touch(run_root / "t11_relation_repair_candidates.gpkg")
        _touch(run_root / "t11_manual_relation_template.csv")
        _touch(run_root / "t11_relation_repair_candidate_summary.json")
        (target_dir / "stdout.log").write_text(
            json.dumps({"run_root": str(run_root)}),
            encoding="utf-8",
        )
        return {"stage_id": stage_id, "status": "passed", "outputs": {}}

    monkeypatch.setattr(t10_case_runner, "_execute_command", fake_execute)
    record, produced = t10_case_runner._run_t11(
        "1885118",
        case_run_dir,
        stage_dir,
        tmp_path,
        Path("/python"),
        handoffs,
    )

    assert record["status"] == "passed"
    assert record["missing_outputs"] == []
    assert captured["stage_id"] == "t11"
    assert captured["command"][1] == "scripts/t11_extract_relation_repair_candidates.py"
    assert captured["command"][captured["command"].index("--t10-case-root") + 1] == str(case_run_dir)
    assert produced["t11_candidates_csv"].endswith("t11_relation_repair_candidates.csv")
    assert produced["t11_summary_json"].endswith("t11_relation_repair_candidate_summary.json")


def test_t11_case_stage_blocks_without_t06_outputs(tmp_path: Path) -> None:
    case_run_dir = tmp_path / "case"
    case_run_dir.mkdir()

    record, produced = t10_case_runner._run_t11(
        "1885118",
        case_run_dir,
        case_run_dir / "t11",
        tmp_path,
        Path("/python"),
        {},
    )

    assert record["status"] == "blocked"
    assert set(record["missing_inputs"]) == {
        "t06_step3_summary",
        "t06_frcsd_road",
        "t06_frcsd_node",
        "t06_segment_relation",
    }
    assert produced == {}


def test_innernet_t11_input_discovery_prefers_fixed_full_pipeline_paths(tmp_path: Path) -> None:
    expected_nodes = _touch(tmp_path / "t04_internal_full_input" / "t04_full" / "nodes.gpkg")
    expected_t03_anchor = _touch(
        tmp_path / "t03_internal_full_input" / "t03_full" / "nodes_anchor_update_audit.csv"
    )
    expected_t04_anchor = _touch(
        tmp_path / "t04_internal_full_input" / "t04_full" / "nodes_anchor_update_audit.csv"
    )
    _touch(tmp_path / "aaa_decoy" / "nodes.gpkg")
    _touch(tmp_path / "aaa_decoy" / "nodes_anchor_update_audit.csv")

    inputs = _discover_inputs(tmp_path)

    assert inputs["final_nodes"] == expected_nodes
    assert inputs["t03_anchor_audit"] == expected_t03_anchor
    assert inputs["t04_anchor_audit"] == expected_t04_anchor


def test_innernet_full_pipeline_keeps_t11_before_optional_t12_and_t09() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "scripts" / "t10_run_innernet_full_pipeline.sh").read_text(encoding="utf-8")

    assert (
        "ordered=(t08_preprocess t01 t07_step12 t03 t04 t05 "
        "t06_step12 t06_step3 t11 t12 t09)"
    ) in script
    assert 't11|t11_candidates) printf \'%s\\n\' "t11" ;;' in script
    t11_region = script.split('T11_OUT_ROOT="$RUN_ROOT/t11_manual_relation_review"', 1)[1].split(
        'T09_OUT_ROOT="$RUN_ROOT/t09_swsd_field_rule_restoration"', 1
    )[0]
    assert "run_logged t11" in t11_region
    assert '--t10-case-root "$RUN_ROOT"' in t11_region
    assert "manifest_stage_record t11 T11 passed" in t11_region


def test_finalize_existing_requires_t11_stage_and_outputs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    run_root = tmp_path / "legacy_run"
    frcsd_road = _touch(
        run_root
        / "t06_segment_fusion_precheck"
        / "t06_innernet_precheck"
        / "step3_segment_replacement"
        / "t06_frcsd_road.gpkg"
    )
    frcsd_node = _touch(frcsd_road.with_name("t06_frcsd_node.gpkg"))
    restriction = _touch(run_root / "t09_swsd_field_rule_restoration" / "t09_step3" / "frcsd_restriction.gpkg")
    manifest = {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "repo_dir": str(repo_root),
        "created_at_utc": "2026-07-13T00:00:00+00:00",
        "status": "running",
        "passed": False,
        "inputs": {},
        "outputs": {
            "t06_frcsd_road": str(frcsd_road),
            "t06_frcsd_node": str(frcsd_node),
            "t09_frcsd_restriction": str(restriction),
        },
        "stage_order": ["t06_step3", "t09"],
        "stages": {"t06_step3": {"status": "passed"}, "t09": {"status": "passed"}},
    }
    (run_root / "t10_innernet_full_pipeline_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/t10_run_innernet_full_pipeline.sh"],
        cwd=repo_root,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHON_BIN": sys.executable,
            "REPO_DIR": str(repo_root),
            "FINALIZE_EXISTING": "1",
            "RESUME_RUN_ROOT": str(run_root),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    summary = json.loads((run_root / "t10_innernet_full_pipeline_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert set(summary["missing_final_outputs"]) == {
        "t11_candidates_csv",
        "t11_summary_json",
        "t11_stage",
    }
