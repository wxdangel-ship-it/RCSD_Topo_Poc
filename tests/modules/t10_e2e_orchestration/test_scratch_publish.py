from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from shapely.geometry import Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t10_e2e_orchestration.scratch_publish import (
    _decode_windows_output,
    _extract_archive_with_windows_tar,
    publish_t10_scratch_run,
)


def test_publish_t10_scratch_run_preserves_tree_and_rebases_paths(tmp_path: Path) -> None:
    scratch_out_root = tmp_path / "scratch"
    final_out_root = tmp_path / "final"
    run_root = scratch_out_root / "run-1"
    surface_path = (
        run_root
        / "cases"
        / "1885118"
        / "t03"
        / "t03"
        / "virtual_intersection_polygons.gpkg"
    )
    source_case_dir = run_root / "cases" / "1885118" / "t03" / "t03" / "cases" / "100"
    surface_path.parent.mkdir(parents=True)
    write_vector(
        surface_path,
        [
            {
                "properties": {"case_id": "100", "source_case_dir": str(source_case_dir)},
                "geometry": Point(1.0, 2.0),
            }
        ],
    )
    for name in ("t10_e2e_run_summary.json", "t10_e2e_run_manifest.json"):
        (run_root / name).write_text(
            json.dumps(
                {
                    "run_root": str(run_root),
                    "duration_seconds": 12.5,
                    "result": str(run_root / "result.gpkg"),
                }
            ),
            encoding="utf-8",
        )

    result = publish_t10_scratch_run(
        scratch_out_root=scratch_out_root,
        final_out_root=final_out_root,
        run_id="run-1",
        keep_scratch=True,
        prefer_windows_tar=False,
    )

    final_run_root = final_out_root / "run-1"
    summary = json.loads((final_run_root / "t10_e2e_run_summary.json").read_text(encoding="utf-8"))
    assert result["source_file_count"] == result["published_file_count"] == 3
    assert result["gpkg_rebased_row_count"] == 1
    assert summary["run_root"] == str(final_run_root)
    assert summary["performance"]["scratch_execution_seconds"] == 12.5
    assert summary["duration_seconds"] > 12.5
    with sqlite3.connect(
        final_run_root
        / "cases"
        / "1885118"
        / "t03"
        / "t03"
        / "virtual_intersection_polygons.gpkg"
    ) as connection:
        table_name = connection.execute(
            "SELECT table_name FROM gpkg_geometry_columns LIMIT 1"
        ).fetchone()[0]
        value = connection.execute(
            f'SELECT source_case_dir FROM "{table_name}"'
        ).fetchone()[0]
    assert value.startswith(str(final_run_root))
    assert run_root.is_dir()


@pytest.mark.parametrize("run_id", ["", ".", "..", "nested/run"])
def test_publish_t10_scratch_run_rejects_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="Unsafe T10 run_id"):
        publish_t10_scratch_run(
            scratch_out_root=tmp_path / "scratch",
            final_out_root=tmp_path / "final",
            run_id=run_id,
        )


def test_windows_tar_exec_failure_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t10_e2e_orchestration.scratch_publish.shutil.which",
        lambda name: f"/fake/{name}",
    )
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t10_e2e_orchestration.scratch_publish.subprocess.check_output",
        lambda *args, **kwargs: "E:\\fake\n",
    )

    def fail_exec(*args, **kwargs):
        raise OSError("WSL interop disabled")

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t10_e2e_orchestration.scratch_publish.subprocess.run",
        fail_exec,
    )

    assert _extract_archive_with_windows_tar(
        Path("/mnt/e/archive.tar"),
        Path("/mnt/e/output"),
    ) is False


def test_decode_windows_output_accepts_utf16le() -> None:
    payload = "T10_FINALIZE|3|100|2|7\r\n".encode("utf-16le")

    assert _decode_windows_output(payload).startswith("T10_FINALIZE|3|100")
