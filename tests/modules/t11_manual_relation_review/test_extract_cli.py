from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "t11_extract_relation_repair_candidates.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("t11_extract_relation_repair_candidates_cli", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifacts(root: Path, case_id: str) -> SimpleNamespace:
    run_root = root / case_id / "run_test"
    return SimpleNamespace(
        run_root=run_root,
        candidate_count=1,
        candidates_csv=run_root / "candidates.csv",
        manual_template_csv=run_root / "manual.csv",
        anchor_audit_csv=None,
        anchor_manual_template_csv=None,
        all_1v1_not_replaced_csv=None,
        all_1v1_not_replaced_gpkg=None,
        all_1v1_not_replaced_xlsx=None,
        unreplaced_relation_gap_csv=None,
        unreplaced_relation_gap_gpkg=None,
        unreplaced_relation_gap_xlsx=None,
        all_evidence_relation_gap_xlsx=None,
        no_evidence_relation_gap_xlsx=None,
        summary_json=run_root / "summary.json",
    )


def test_single_case_cli_remains_compatible(tmp_path: Path, monkeypatch, capsys) -> None:
    cli = _load_cli()
    calls = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return _artifacts(tmp_path, kwargs["case_id"])

    monkeypatch.setattr(cli, "extract_t11_relation_repair_candidates", fake_extract)
    status = cli.main(
        [
            "--t10-case-root",
            str(tmp_path / "case"),
            "--out-root",
            str(tmp_path / "output"),
            "--case-id",
            "1885118",
        ]
    )

    assert status == 0
    assert calls == [
        {
            "t10_case_root": tmp_path / "case",
            "out_root": tmp_path / "output",
            "case_id": "1885118",
            "existing_manual_csv_path": None,
        }
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] == 1
    assert "mode" not in payload


def test_batch_cli_preserves_case_order_and_isolates_outputs(tmp_path: Path, monkeypatch, capsys) -> None:
    cli = _load_cli()
    suite_root = tmp_path / "suite"
    for case_id in ("1885118", "605415675"):
        (suite_root / case_id).mkdir(parents=True)
    calls = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return _artifacts(tmp_path, kwargs["case_id"])

    monkeypatch.setattr(cli, "extract_t11_relation_repair_candidates", fake_extract)
    status = cli.main(
        [
            "--t10-suite-root",
            str(suite_root),
            "--out-root",
            str(tmp_path / "output"),
            "--case-ids",
            "1885118",
            "605415675",
            "--workers",
            "2",
        ]
    )

    assert status == 0
    assert {item["case_id"] for item in calls} == {"1885118", "605415675"}
    assert {item["out_root"] for item in calls} == {
        tmp_path / "output" / "1885118",
        tmp_path / "output" / "605415675",
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "batch"
    assert payload["workers"] == 2
    assert [item["case_id"] for item in payload["cases"]] == ["1885118", "605415675"]


@pytest.mark.parametrize("workers", ["0", "9"])
def test_batch_cli_rejects_unsafe_worker_count(workers: str, tmp_path: Path) -> None:
    cli = _load_cli()
    with pytest.raises(SystemExit, match="2"):
        cli.main(
            [
                "--t10-suite-root",
                str(tmp_path),
                "--out-root",
                str(tmp_path / "output"),
                "--workers",
                workers,
            ]
        )


def test_batch_cli_rejects_single_manual_csv(tmp_path: Path) -> None:
    cli = _load_cli()
    with pytest.raises(SystemExit, match="2"):
        cli.main(
            [
                "--t10-suite-root",
                str(tmp_path),
                "--out-root",
                str(tmp_path / "output"),
                "--existing-manual-csv",
                str(tmp_path / "manual.csv"),
            ]
        )
