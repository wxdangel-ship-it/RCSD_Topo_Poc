from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import batch_runner


def test_batch_runner_writes_failure_docs_with_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(case_id="broken_case")

    monkeypatch.setattr(
        batch_runner,
        "load_case_specs",
        lambda **_kwargs: ([spec], {"selected_case_count": 1, "selected_case_ids": ["broken_case"]}),
    )

    def _raise_case_failure(_spec):
        raise RuntimeError("synthetic load failure")

    monkeypatch.setattr(batch_runner, "load_case_bundle", _raise_case_failure)
    monkeypatch.setattr(batch_runner, "write_step7_batch_outputs", lambda **_kwargs: {})

    run_root = batch_runner.run_t04_step14_batch(
        case_root=tmp_path / "cases",
        out_root=tmp_path / "out",
        run_id="failure_observability",
    )

    failure_doc_path = run_root / "failures" / "broken_case.failure.json"
    failure_doc = json.loads(failure_doc_path.read_text(encoding="utf-8"))
    batch_failures = json.loads((run_root / "batch_failures.json").read_text(encoding="utf-8"))
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))

    assert failure_doc["case_id"] == "broken_case"
    assert failure_doc["exception_type"] == "RuntimeError"
    assert "synthetic load failure" in failure_doc["message"]
    assert "Traceback" in failure_doc["traceback"]
    assert batch_failures["failed_case_ids"] == ["broken_case"]
    assert summary["failed_case_ids"] == ["broken_case"]
    assert summary["failed_cases"][0]["exception_type"] == "RuntimeError"
    assert summary["failed_cases"][0]["failure_doc_path"] == str(failure_doc_path)


def test_batch_runner_records_closeout_failure_without_aborting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = SimpleNamespace(case_id="grid_guard_case")
    case_result = SimpleNamespace(case_spec=spec)

    monkeypatch.setattr(
        batch_runner,
        "load_case_specs",
        lambda **_kwargs: ([spec], {"selected_case_count": 1, "selected_case_ids": ["grid_guard_case"]}),
    )
    monkeypatch.setattr(batch_runner, "load_case_bundle", lambda _spec: object())
    monkeypatch.setattr(batch_runner, "build_case_result", lambda _bundle: case_result)
    monkeypatch.setattr(batch_runner, "resolve_step4_final_conflicts", lambda results: (results, {}))
    monkeypatch.setattr(batch_runner, "apply_road_surface_fork_binding", lambda results: (results, {}))
    monkeypatch.setattr(batch_runner, "apply_rcsd_anchored_reverse_lookup", lambda results: (results, {}))
    monkeypatch.setattr(batch_runner, "apply_step4_arbitration_to_case_results", lambda results: results)
    monkeypatch.setattr(batch_runner, "materialize_review_gallery", lambda _run_root, rows: rows)
    monkeypatch.setattr(batch_runner, "write_review_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_runner, "write_review_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_runner, "write_step7_batch_outputs", lambda **_kwargs: {})

    def _raise_closeout_failure(*_args, **_kwargs):
        raise ValueError("step6_grid_too_large: synthetic guard")

    monkeypatch.setattr(batch_runner, "write_case_outputs", _raise_closeout_failure)

    run_root = batch_runner.run_t04_step14_batch(
        case_root=tmp_path / "cases",
        out_root=tmp_path / "out",
        run_id="closeout_failure_observability",
    )

    failure_doc_path = run_root / "failures" / "grid_guard_case.failure.json"
    failure_doc = json.loads(failure_doc_path.read_text(encoding="utf-8"))
    batch_failures = json.loads((run_root / "batch_failures.json").read_text(encoding="utf-8"))
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))

    assert failure_doc["exception_type"] == "ValueError"
    assert "step6_grid_too_large" in failure_doc["message"]
    assert batch_failures["failed_case_ids"] == ["grid_guard_case"]
    assert summary["failed_case_ids"] == ["grid_guard_case"]
    assert summary["performance"]["runtime_failed_case_count"] == 1


def test_run_root_guard_rejects_repository_root() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    with pytest.raises(ValueError, match="unsafe run_root"):
        batch_runner._assert_safe_run_root(
            run_root=repo_root,
            out_root=repo_root.parent,
            run_id=repo_root.name,
        )
