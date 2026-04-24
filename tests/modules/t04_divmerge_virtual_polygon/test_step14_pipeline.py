from __future__ import annotations

from pathlib import Path


def test_step14_pipeline_split_test_files_are_registered() -> None:
    test_dir = Path(__file__).parent
    expected_split_files = {
        "test_step14_synthetic_batch.py",
        "test_positive_rcsd_selection.py",
        "test_step14_real_anchor2.py",
        "test_step14_real_regression.py",
        "test_step14_support.py",
    }

    missing = sorted(name for name in expected_split_files if not (test_dir / name).is_file())
    assert missing == []
