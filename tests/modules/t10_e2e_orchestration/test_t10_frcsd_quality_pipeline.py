from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "t10_run_frcsd_quality_pipeline.sh"
FULL_PIPELINE_PATH = REPO_ROOT / "scripts" / "t10_run_innernet_full_pipeline.sh"


def test_frcsd_quality_profile_is_a_thin_fixed_wrapper() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "export RUN_T08=0" in script
    assert "export RUN_T12=1" in script
    assert 'export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"' in script
    assert (
        "stages=t01,t07_step12,t03,t04,t05,t06_step12,t06_step3,t11,t12,t09"
        in script
    )
    assert 'exec bash "$REPO_DIR/scripts/t10_run_innernet_full_pipeline.sh"' in script
    assert "scripts/t12_run_frcsd_quality_audit.py" not in script


def test_full_pipeline_forwards_optional_t12_case_manifest() -> None:
    script = FULL_PIPELINE_PATH.read_text(encoding="utf-8")

    assert 'T12_CASE_MANIFEST="${T12_CASE_MANIFEST:-}"' in script
    assert 'T12_ARGS+=(--case-manifest "$T12_CASE_MANIFEST")' in script
    assert '"inputs.case_manifest=$T12_CASE_MANIFEST"' in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
def test_frcsd_quality_profile_help_and_preflight_blocks() -> None:
    help_result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T11 -> T12 -> T09" in help_result.stdout

    base_env = os.environ.copy()
    for key in (
        "RUN_T08",
        "RUN_T12",
        "FRCSD_1V1_ROADS_PATH",
        "FRCSD_1V1_NODES_PATH",
        "FINALIZE_EXISTING",
        "RESUME_RUN_ROOT",
        "RESUME_FROM_STAGE",
        "RUN_STAGES",
    ):
        base_env.pop(key, None)
    missing_result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        env=base_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing_result.returncode == 2
    assert "requires FRCSD_1V1_ROADS_PATH and FRCSD_1V1_NODES_PATH" in missing_result.stderr

    conflict_env = dict(base_env, RUN_T08="1")
    conflict_result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        env=conflict_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert conflict_result.returncode == 2
    assert "requires RUN_T08=0" in conflict_result.stderr
