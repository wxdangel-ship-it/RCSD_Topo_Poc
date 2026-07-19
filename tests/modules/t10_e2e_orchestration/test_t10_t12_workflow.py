from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t10_e2e_orchestration import case_runner
from rcsd_topo_poc.modules.t10_e2e_orchestration.contracts import (
    EXTERNAL_INPUT_REQUIREMENTS,
    T10_V1_CHAIN,
    T10_V1_CHAIN_WITH_T12,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_t12_is_optional_and_inserted_between_t11_and_t09() -> None:
    assert "t12" not in case_runner._t10_stage_order(False)
    assert "t12_frcsd_quality_audit" not in T10_V1_CHAIN
    order = case_runner._t10_stage_order(True)

    assert order[order.index("t06_step3") + 1] == "t11"
    assert order[order.index("t11") + 1] == "t12"
    assert order[order.index("t12") + 1] == "t09_step12"
    assert T10_V1_CHAIN_WITH_T12[
        T10_V1_CHAIN_WITH_T12.index("t11_manual_relation_review") + 1
    ] == "t12_frcsd_quality_audit"
    assert case_runner.T10_E2E_STAGE_MODULES["t12"] == "t12_frcsd_quality_audit"


def test_t12_external_slots_are_explicit_and_optional_for_legacy_packages() -> None:
    requirements = {item.slot: item for item in EXTERNAL_INPUT_REQUIREMENTS}

    assert requirements["frcsd_1v1_roads"].required is False
    assert requirements["frcsd_1v1_nodes"].required is False
    assert requirements["rcsdroad"].required is True
    assert requirements["rcsdnode"].required is True


def test_t12_case_stage_invokes_entry_and_publishes_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stage_dir = tmp_path / "case" / "t12"
    t05_phase2 = tmp_path / "case" / "t05" / "t05_phase2"
    t06_root = tmp_path / "case" / "t06_step12" / "t06"
    t06_root.mkdir(parents=True)
    external_inputs = {
        "frcsd_1v1_roads": _touch(tmp_path / "inputs" / "frcsd_roads.gpkg"),
        "frcsd_1v1_nodes": _touch(tmp_path / "inputs" / "frcsd_nodes.gpkg"),
        "rcsd_intersection": _touch(tmp_path / "inputs" / "intersection.gpkg"),
        "drivezone": _touch(tmp_path / "inputs" / "drivezone.gpkg"),
    }
    handoffs = {
        "t01_segment": str(_touch(tmp_path / "case" / "t01" / "segment.gpkg")),
        "t01_roads": str(_touch(tmp_path / "case" / "t01" / "roads.gpkg")),
        "final_swsd_nodes": str(_touch(tmp_path / "case" / "t04" / "nodes.gpkg")),
        "t05_phase2_root": str(t05_phase2),
        "t06_run_root": str(t06_root),
    }
    _touch(t05_phase2 / "intersection_match_all_audit.csv")
    case_manifest = _touch(tmp_path / "package" / "t10_case_evidence_manifest.json")
    review = _touch(tmp_path / "review.csv")
    captured: dict[str, object] = {}

    def fake_execute(stage_id, actual_stage_dir, repo_root, command, env, inputs):
        captured.update(stage_id=stage_id, command=command, inputs=inputs)
        run_root = actual_stage_dir / "t12_1026960"
        for name in (
            "t12_frcsd_quality_audit_manifest.json",
            "t12_frcsd_quality_audit_summary.json",
            "t12_frcsd_quality_candidates.csv",
            "t12_frcsd_quality_candidates.gpkg",
            "t12_frcsd_confirmed_quality_issues.csv",
            "t12_frcsd_confirmed_quality_issues.gpkg",
            "t12_frcsd_quality_review_exclusions.csv",
            "t12_frcsd_quality_manual_review_required.csv",
        ):
            _touch(run_root / name)
        return {"stage_id": stage_id, "status": "passed"}

    monkeypatch.setattr(case_runner, "_execute_command", fake_execute)

    record, produced = case_runner._run_t12(
        "1026960",
        stage_dir,
        tmp_path,
        "python",
        external_inputs,
        handoffs,
        case_manifest_path=case_manifest,
        review_decisions_path=review,
    )

    assert record["status"] == "passed"
    assert record["audit_only"] is True
    assert captured["stage_id"] == "t12"
    command = captured["command"]
    assert command[1] == "scripts/t12_run_frcsd_quality_audit.py"
    assert "--frcsd-roads" in command
    assert "--review-decisions" in command
    assert produced["t12_summary_json"].endswith("t12_frcsd_quality_audit_summary.json")


def test_t12_case_stage_blocks_without_explicit_frcsd_slots(tmp_path: Path) -> None:
    record, produced = case_runner._run_t12(
        "case",
        tmp_path / "t12",
        tmp_path,
        "python",
        {},
        {},
    )

    assert record["status"] == "blocked"
    assert "frcsd_1v1_roads" in record["missing_inputs"]
    assert "frcsd_1v1_nodes" in record["missing_inputs"]
    assert produced == {}


def test_case_shell_exposes_t12_without_changing_default() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "scripts" / "t10_run_e2e_cases.sh").read_text(
        encoding="utf-8"
    )

    assert 'RUN_T12="${RUN_T12:-0}"' in script
    assert "ARGS+=(--run-t12)" in script
    assert 'ARGS+=(--t12-review-decisions "$T12_REVIEW_DECISIONS")' in script


def test_full_runner_declares_t12_resume_manifest_and_finalize_contract() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "scripts" / "t10_run_innernet_full_pipeline.sh").read_text(
        encoding="utf-8"
    )

    assert 'RUN_T12="${RUN_T12:-0}"' in script
    assert 'T12_RUN_ID="${T12_RUN_ID:-t12_full}"' in script
    assert 'T12_PROCESSING_CRS="${T12_PROCESSING_CRS:-}"' in script
    assert '*((' + '"T08",) if os.getenv("RUN_T08")=="1" else ()),' in script
    assert '*(("T12",) if os.getenv("RUN_T12")=="1" else ()),' in script
    assert 't12|t12_quality) printf \'%s\\n\' "t12" ;;' in script
    assert "ordered=(t08_preprocess t01 t07_step12 t03 t04 t05 t06_step12 t06_step3 t11 t12 t09)" in script
    t11_position = script.index('T11_OUT_ROOT="$RUN_ROOT/t11_manual_relation_review"')
    t12_position = script.index('T12_OUT_ROOT="$RUN_ROOT/t12_frcsd_quality_audit"')
    t09_position = script.index('T09_OUT_ROOT="$RUN_ROOT/t09_swsd_field_rule_restoration"')
    assert t11_position < t12_position < t09_position
    t12_region = script[t12_position:t09_position]
    assert "if should_run_t12; then" in t12_region
    assert "run_logged t12" in t12_region
    assert "manifest_stage_record t12 T12 passed" in t12_region
    assert '--frcsd-roads "$FRCSD_1V1_ROADS_PATH"' in t12_region
    assert 'T12_ARGS+=(--processing-crs "$T12_PROCESSING_CRS")' in t12_region
    assert '"params.processing_crs=$T12_PROCESSING_CRS"' in t12_region
    assert 'T12_PROCESSING_CRS="$(manifest_get params t12_processing_crs "")"' in script
    assert 'manifest_set params t12_processing_crs "$T12_PROCESSING_CRS"' in script
    assert '"t12_enabled": os.environ.get("RUN_T12") == "1"' in script
    assert 'missing_final_outputs.append("t12_stage")' in script
    assert 'T08_STAGE_STATUS="skipped"' not in script
