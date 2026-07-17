from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t08_preprocess import (
    DEFAULT_EXPERIMENT_PATCH_IDS,
    FRCSD_FILE_NAMES,
    T08PatchDataOrganizationError,
    run_t08_patch_data_organization,
)
from rcsd_topo_poc.modules.t08_preprocess import patch_data_organization as tool11_module


def _make_patch(source_root: Path, patch_id: str, *, marker: str | None = None) -> Path:
    marker = marker or patch_id
    patch_dir = source_root / patch_id
    swsd_root = patch_dir / "SD_City" / "target_level1"
    rcsd_root = patch_dir / "SD_City" / "base_origin"
    frcsd_root = patch_dir / "rc_sw_gd_merge"
    (swsd_root / "nested").mkdir(parents=True)
    (swsd_root / "empty").mkdir()
    rcsd_root.mkdir(parents=True)
    frcsd_root.mkdir(parents=True)
    (swsd_root / "node.geojson").write_text(f"swsd-node-{marker}", encoding="utf-8")
    (swsd_root / "nested" / "road.bin").write_bytes(f"swsd-road-{marker}".encode("utf-8"))
    (rcsd_root / "base.txt").write_text(f"rcsd-{marker}", encoding="utf-8")
    for file_name in FRCSD_FILE_NAMES:
        (frcsd_root / file_name).write_text(f"{file_name}-{marker}", encoding="utf-8")
    (frcsd_root / "ignored.geojson").write_text("must-not-copy", encoding="utf-8")
    (frcsd_root / "ignored_dir").mkdir()
    (frcsd_root / "ignored_dir" / "also_ignored.txt").write_text("ignored", encoding="utf-8")
    return patch_dir


def _relative_tree(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() + ("/" if path.is_dir() else "")
        for path in root.rglob("*")
    }


def test_tool11_organizes_all_patches_and_default_experiment_subset(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    all_patch_ids = [*DEFAULT_EXPERIMENT_PATCH_IDS, "9999999999999999"]
    for patch_id in all_patch_ids:
        _make_patch(source_root, patch_id)
    (source_root / "README.txt").write_text("root note", encoding="utf-8")
    (source_root / "notes").mkdir()
    output_root = tmp_path / "organized"
    experiment_root = tmp_path / "experiment"

    artifacts = run_t08_patch_data_organization(
        source_root=source_root,
        output_root=output_root,
        experiment_output_root=experiment_root,
        progress_interval_files=2,
    )

    assert {path.name for path in output_root.iterdir()} == set(all_patch_ids)
    assert {path.name for path in experiment_root.iterdir()} == set(DEFAULT_EXPERIMENT_PATCH_IDS)
    for patch_id in all_patch_ids:
        target_patch = output_root / patch_id
        assert (target_patch / "SWSD" / "node.geojson").read_text(encoding="utf-8") == f"swsd-node-{patch_id}"
        assert (target_patch / "SWSD" / "nested" / "road.bin").read_bytes() == f"swsd-road-{patch_id}".encode("utf-8")
        assert (target_patch / "SWSD" / "empty").is_dir()
        assert (target_patch / "RCSD" / "base.txt").read_text(encoding="utf-8") == f"rcsd-{patch_id}"
        assert {path.name for path in (target_patch / "FRCSD").iterdir()} == set(FRCSD_FILE_NAMES)
        assert not (target_patch / "FRCSD" / "ignored.geojson").exists()
    for patch_id in DEFAULT_EXPERIMENT_PATCH_IDS:
        assert _relative_tree(experiment_root / patch_id) == _relative_tree(output_root / patch_id)
    assert not (experiment_root / "9999999999999999").exists()
    assert (source_root / "README.txt").is_file()

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["counts"]["patch_count"] == len(all_patch_ids)
    assert summary["counts"]["experiment_patch_count"] == 6
    assert summary["counts"]["source_file_count"] == len(all_patch_ids) * 6
    assert summary["counts"]["experiment_output_file_count"] == 6 * 6
    assert summary["counts"]["frcsd_file_count"] == len(all_patch_ids) * 3
    assert summary["root_audit"]["ignored_entries"] == ["README.txt", "notes/"]
    assert summary["integrity_audit"]["passed"] is True
    assert summary["integrity_audit"]["all_file_hashes_verified"] is True
    assert summary["integrity_audit"]["main_patch_ids_exact"] is True
    assert summary["integrity_audit"]["main_file_set_exact"] is True
    assert summary["integrity_audit"]["main_directory_set_exact"] is True
    assert summary["integrity_audit"]["experiment_file_set_exact"] is True
    assert summary["integrity_audit"]["experiment_directory_set_exact"] is True
    assert summary["gis_audit"] == {
        "crs": "copied_without_transformation",
        "topology": "no_topology_operation",
        "geometry_semantics": "byte_preserving_copy_verified_by_sha256",
        "silent_fix_applied": False,
    }
    assert summary["performance"]["bytes_per_second"] >= 0
    assert artifacts.summary_json.stem.endswith("_tool11")
    assert artifacts.experiment_output_root == experiment_root.resolve()
    assert all(row["verified"] for row in summary["file_audit"])
    experiment_rows = [row for row in summary["file_audit"] if row["experiment_output_path"]]
    assert experiment_rows
    assert all(
        row["source_sha256"]
        == row["main_output_sha256"]
        == row["experiment_output_sha256"]
        for row in experiment_rows
    )


def test_tool11_organizes_all_patches_without_experiment_output(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    for patch_id in ("100", "200"):
        _make_patch(source_root, patch_id)
    output_root = tmp_path / "organized"

    artifacts = run_t08_patch_data_organization(
        source_root=source_root,
        output_root=output_root,
        progress_interval_files=1,
    )

    assert {path.name for path in output_root.iterdir()} == {"100", "200"}
    assert artifacts.experiment_output_root is None
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["outputs"]["experiment_output_root"] is None
    assert summary["parameters"]["experiment_enabled"] is False
    assert summary["parameters"]["experiment_patch_ids"] == []
    assert summary["counts"]["experiment_patch_count"] == 0
    assert summary["counts"]["experiment_output_file_count"] == 0
    assert summary["publication"]["main_output_published"] is True
    assert summary["publication"]["experiment_output_requested"] is False
    assert summary["publication"]["experiment_output_published"] is False
    assert summary["integrity_audit"]["experiment_output_requested"] is False
    assert summary["integrity_audit"]["experiment_file_set_exact"] is None
    assert summary["integrity_audit"]["experiment_directory_set_exact"] is None
    assert all(row["experiment_output_path"] is None for row in summary["file_audit"])


def test_tool11_rejects_experiment_patch_ids_without_experiment_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _make_patch(source_root, "100")

    with pytest.raises(
        T08PatchDataOrganizationError,
        match="experiment_patch_ids requires experiment_output_root",
    ):
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=tmp_path / "organized",
            experiment_patch_ids=("100",),
        )


def test_tool11_collects_all_patch_preflight_errors_without_partial_outputs(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    patch_a = _make_patch(source_root, "100")
    patch_b = _make_patch(source_root, "200")
    (patch_a / "rc_sw_gd_merge" / "RCSDRoad.geojson").unlink()
    shutil.rmtree(patch_b / "SD_City" / "base_origin")
    output_root = tmp_path / "organized"
    experiment_root = tmp_path / "experiment"

    with pytest.raises(T08PatchDataOrganizationError) as caught:
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=output_root,
            experiment_output_root=experiment_root,
            experiment_patch_ids=("100", "200"),
        )

    error = caught.value
    assert "Patch 100 missing FRCSD file" in str(error)
    assert "Patch 200 missing RCSD source directory" in str(error)
    assert not output_root.exists()
    assert not experiment_root.exists()
    assert error.summary_json is not None and error.summary_json.is_file()
    summary = json.loads(error.summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["publication"]["main_output_published"] is False
    assert any("Patch 100 missing FRCSD file" in issue for issue in summary["preflight_issues"])
    assert any("Patch 200 missing RCSD source directory" in issue for issue in summary["preflight_issues"])
    assert {row["patch_id"]: row["status"] for row in summary["patches"]} == {
        "100": "invalid",
        "200": "invalid",
    }


def test_tool11_rejects_existing_roots_then_atomically_overwrites(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    patch_dir = _make_patch(source_root, "100", marker="first")
    output_root = tmp_path / "organized"
    experiment_root = tmp_path / "experiment"
    run_t08_patch_data_organization(
        source_root=source_root,
        output_root=output_root,
        experiment_output_root=experiment_root,
        experiment_patch_ids=("100",),
    )
    original = (output_root / "100" / "SWSD" / "node.geojson").read_bytes()
    (output_root / "stale.txt").write_text("stale", encoding="utf-8")
    (experiment_root / "stale.txt").write_text("stale", encoding="utf-8")
    (patch_dir / "SD_City" / "target_level1" / "node.geojson").write_text(
        "swsd-node-second",
        encoding="utf-8",
    )

    with pytest.raises(T08PatchDataOrganizationError, match="already exists"):
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=output_root,
            experiment_output_root=experiment_root,
            experiment_patch_ids=("100",),
        )
    assert (output_root / "100" / "SWSD" / "node.geojson").read_bytes() == original
    assert (output_root / "stale.txt").is_file()

    run_t08_patch_data_organization(
        source_root=source_root,
        output_root=output_root,
        experiment_output_root=experiment_root,
        experiment_patch_ids=("100",),
        overwrite=True,
    )
    assert (output_root / "100" / "SWSD" / "node.geojson").read_text(encoding="utf-8") == "swsd-node-second"
    assert (experiment_root / "100" / "SWSD" / "node.geojson").read_text(encoding="utf-8") == "swsd-node-second"
    assert not (output_root / "stale.txt").exists()
    assert not (experiment_root / "stale.txt").exists()
    assert not list(tmp_path.glob(".*.tool11.*"))


def test_tool11_publish_failure_rolls_back_existing_main_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    patch_dir = _make_patch(source_root, "100", marker="first")
    output_root = tmp_path / "organized"
    experiment_root = tmp_path / "experiment"
    run_t08_patch_data_organization(
        source_root=source_root,
        output_root=output_root,
        experiment_output_root=experiment_root,
        experiment_patch_ids=("100",),
    )
    old_main = (output_root / "100" / "SWSD" / "node.geojson").read_bytes()
    old_experiment = (experiment_root / "100" / "SWSD" / "node.geojson").read_bytes()
    (patch_dir / "SD_City" / "target_level1" / "node.geojson").write_text(
        "swsd-node-new",
        encoding="utf-8",
    )
    original_publish = tool11_module._publish_staged_path

    def fail_experiment_publish(
        staged_path: Path,
        final_path: Path,
        *,
        run_token: str,
        overwrite: bool,
    ) -> object:
        if final_path == experiment_root.resolve():
            raise OSError("injected experiment publish failure")
        return original_publish(
            staged_path,
            final_path,
            run_token=run_token,
            overwrite=overwrite,
        )

    monkeypatch.setattr(tool11_module, "_publish_staged_path", fail_experiment_publish)
    with pytest.raises(T08PatchDataOrganizationError, match="injected experiment publish failure"):
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=output_root,
            experiment_output_root=experiment_root,
            experiment_patch_ids=("100",),
            overwrite=True,
        )

    assert (output_root / "100" / "SWSD" / "node.geojson").read_bytes() == old_main
    assert (experiment_root / "100" / "SWSD" / "node.geojson").read_bytes() == old_experiment
    assert not list(tmp_path.glob(".*.tool11.*"))


def test_tool11_rejects_overlapping_roots_and_writes_summary_outside_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _make_patch(source_root, "100")
    nested_output = source_root / "organized"
    experiment_root = tmp_path / "experiment"

    with pytest.raises(T08PatchDataOrganizationError, match="must not overlap") as caught:
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=nested_output,
            experiment_output_root=experiment_root,
            experiment_patch_ids=("100",),
        )

    assert caught.value.summary_json is not None
    assert source_root.resolve() not in caught.value.summary_json.resolve().parents
    assert not nested_output.exists()
    assert not experiment_root.exists()


def test_tool11_rejects_symlink_in_copied_tree(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    patch_dir = _make_patch(source_root, "100")
    link_path = patch_dir / "SD_City" / "target_level1" / "linked.geojson"
    try:
        os.symlink(
            patch_dir / "SD_City" / "target_level1" / "node.geojson",
            link_path,
        )
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(T08PatchDataOrganizationError, match="contains symlink"):
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=tmp_path / "organized",
            experiment_output_root=tmp_path / "experiment",
            experiment_patch_ids=("100",),
        )


def test_tool11_rejects_special_file_in_copied_tree(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")
    source_root = tmp_path / "source"
    patch_dir = _make_patch(source_root, "100")
    fifo_path = patch_dir / "SD_City" / "base_origin" / "input.fifo"
    os.mkfifo(fifo_path)

    with pytest.raises(T08PatchDataOrganizationError, match="contains special file"):
        run_t08_patch_data_organization(
            source_root=source_root,
            output_root=tmp_path / "organized",
            experiment_output_root=tmp_path / "experiment",
            experiment_patch_ids=("100",),
        )


def test_tool11_script_is_parameterized_and_reports_failure_summary(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _make_patch(source_root, "100")
    output_root = tmp_path / "organized"
    experiment_root = tmp_path / "experiment"
    repo_root = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "scripts/t08_tool11_patch_data_organization.py",
        "--source-root",
        str(source_root),
        "--output-root",
        str(output_root),
        "--experiment-output-root",
        str(experiment_root),
        "--experiment-patch-id",
        "100",
        "--progress-interval-files",
        "1",
    ]

    first = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    second = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    help_result = subprocess.run(
        [sys.executable, "scripts/t08_tool11_patch_data_organization.py", "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    artifacts = json.loads(first.stdout)
    assert Path(artifacts["output_root"]) == output_root
    assert Path(artifacts["experiment_output_root"]) == experiment_root
    assert Path(artifacts["summary_json"]).is_file()
    assert "Tool11 processed Patch 100" in first.stderr
    assert second.returncode == 2
    assert "already exists" in second.stderr
    assert "summary_json=" in second.stderr
    assert help_result.returncode == 0
    assert "--experiment-output-root" in help_result.stdout


def test_tool11_innernet_wrapper_defaults_to_full_only() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "scripts/t08_tool11_run_innernet.sh").read_text(
        encoding="utf-8"
    )

    assert r"D:\TestData\数据整理\20260715\20260715\rcsd_tar_gz" in script_text
    assert r"D:\TestData\POC_QA\Patch_all" in script_text
    assert r"D:\TestData\POC_QA\Patch_test" not in script_text
    assert "DEFAULT_EXPERIMENT_OUTPUT_ROOT" not in script_text
    assert "Experiment output: disabled (full-only mode)" in script_text
    for patch_id in DEFAULT_EXPERIMENT_PATCH_IDS:
        assert patch_id in script_text
    assert 'overwrite="${OVERWRITE:-0}"' in script_text
    assert "wslpath -u" in script_text
    assert "t08_tool11_patch_data_organization.py" in script_text


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="The innernet wrapper functional test requires a POSIX bash/WSL process.",
)
def test_tool11_innernet_wrapper_runs_formal_entry_and_refuses_default_overwrite(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    for patch_id in ("100", "200"):
        _make_patch(source_root, patch_id)

    repo_root = Path(__file__).resolve().parents[3]
    output_root = tmp_path / "all"
    first_summary = tmp_path / "first_tool11.json"
    first_log = tmp_path / "first.console.log"
    environment = os.environ.copy()
    environment.update(
        {
            "T08_TOOL11_REPO_ROOT": str(repo_root),
            "T08_TOOL11_SOURCE_ROOT": str(source_root),
            "T08_TOOL11_OUTPUT_ROOT": str(output_root),
            "T08_TOOL11_PYTHON": sys.executable,
            "T08_TOOL11_SUMMARY_OUTPUT": str(first_summary),
            "T08_TOOL11_LOG_FILE": str(first_log),
            "OVERWRITE": "0",
            "PROGRESS_INTERVAL_FILES": "1",
        }
    )

    first = subprocess.run(
        ["bash", "scripts/t08_tool11_run_innernet.sh"],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert first.returncode == 0, first.stdout + first.stderr
    assert output_root.is_dir()
    assert first_summary.is_file()
    assert "[DONE] T08 Tool11 innernet organization passed." in first.stdout
    first_log_text = first_log.read_text(encoding="utf-8")
    assert "Experiment output: disabled (full-only mode)" in first_log_text
    assert "[VERIFY] Requested output roots and the Tool11 audit summary exist." in first_log_text

    second_summary = tmp_path / "second_tool11.json"
    second_log = tmp_path / "second.console.log"
    environment["T08_TOOL11_SUMMARY_OUTPUT"] = str(second_summary)
    environment["T08_TOOL11_LOG_FILE"] = str(second_log)
    second = subprocess.run(
        ["bash", "scripts/t08_tool11_run_innernet.sh"],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert second.returncode == 2
    assert "already exists" in second.stdout
    assert second_summary.is_file()
    assert "[FAILED] T08 Tool11 innernet organization exited with code 2." in second_log.read_text(
        encoding="utf-8"
    )
