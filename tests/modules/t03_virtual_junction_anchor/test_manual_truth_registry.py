from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_batch_runner import (
    run_t03_step3_legal_space_batch,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.t03_batch_runner import (
    run_t03_batch,
)


def _host_path(value: str) -> Path:
    if os.name == "nt":
        return Path(value)
    drive, remainder = value.split(":", 1)
    return Path(f"/mnt/{drive.lower()}{remainder.replace(chr(92), '/')}")


DATA_ROOTS = {
    "qa_t03_error": _host_path(r"E:\TestData\POC_QA\T03_Error"),
    "legacy_t03": _host_path(r"E:\TestData\POC_Data\T03"),
    "legacy_t03_error": _host_path(r"E:\TestData\POC_Data\T03_Error"),
}
TRUTH_PATH = (
    Path(__file__).parent
    / "data"
    / "t03_manual_truth_overrides_20260801.csv"
)
AUDIT_TARGET_PATH = (
    Path(__file__).parent
    / "data"
    / "t03_qa_snapshot_audit_targets_20260802.csv"
)
QA_SNAPSHOT_SHA256 = (
    "9bfea7042a5b208522b137099bc1ed35d6da8a03393819074c58e8f3d71be765"
)


def _load_truth() -> list[dict[str, str]]:
    with TRUTH_PATH.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_audit_targets() -> list[dict[str, str]]:
    with AUDIT_TARGET_PATH.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_manual_truth_registry_is_unique_and_well_formed() -> None:
    rows = _load_truth()
    keys = [(row["dataset_snapshot"], row["case_id"]) for row in rows]
    assert len(keys) == len(set(keys))
    assert {row["expected_step7_state"] for row in rows} <= {
        "accepted",
        "rejected",
    }
    assert all(row["decision_source"] == "user_confirmed" for row in rows)
    assert all(row["decision_reason"] for row in rows)


def test_qa_snapshot_audit_targets_are_fingerprint_scoped() -> None:
    rows = _load_audit_targets()
    keys = [(row["dataset_snapshot"], row["case_id"]) for row in rows]
    assert len(keys) == len(set(keys))
    assert {row["dataset_snapshot"] for row in rows} == {"qa_t03_error"}
    assert {row["input_aggregate_sha256"] for row in rows} == {
        QA_SNAPSHOT_SHA256
    }
    assert all(row["decision_source"] == "data_audit_target" for row in rows)
    assert not (
        set(keys)
        & {
            (row["dataset_snapshot"], row["case_id"])
            for row in _load_truth()
        }
    )


@pytest.mark.skipif(
    not all(path.is_dir() for path in DATA_ROOTS.values()),
    reason="local T03 real-data roots are unavailable",
)
def test_snapshot_truth_and_audit_target_real_case_states(tmp_path: Path) -> None:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in [*_load_truth(), *_load_audit_targets()]:
        grouped[row["dataset_snapshot"]].append(row)

    mismatches: list[dict[str, str]] = []
    for snapshot, rows in sorted(grouped.items()):
        case_ids = sorted({row["case_id"] for row in rows}, key=int)
        case_root = DATA_ROOTS[snapshot]
        missing = [case_id for case_id in case_ids if not (case_root / case_id).is_dir()]
        assert not missing, f"{snapshot} missing truth cases: {missing}"

        step3_root = run_t03_step3_legal_space_batch(
            case_root=case_root,
            case_ids=case_ids,
            workers=4,
            out_root=tmp_path,
            run_id=f"{snapshot}_step3",
        )
        final_root = run_t03_batch(
            case_root=case_root,
            step3_root=step3_root,
            case_ids=case_ids,
            workers=4,
            out_root=tmp_path,
            run_id=f"{snapshot}_final",
        )

        actual_by_case: dict[str, str] = {}
        with (final_root / "t03_review_index.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            for result in csv.DictReader(handle):
                actual_by_case[result["case_id"]] = result["step7_state"]

        for row in rows:
            actual = actual_by_case.get(row["case_id"], "missing")
            if actual != row["expected_step7_state"]:
                mismatches.append(
                    {
                        "dataset_snapshot": snapshot,
                        "case_id": row["case_id"],
                        "expected": row["expected_step7_state"],
                        "actual": actual,
                        "decision_reason": row["decision_reason"],
                    }
                )

    assert not mismatches, mismatches
