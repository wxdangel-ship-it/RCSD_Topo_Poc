from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_inputs import (
    load_junction_sources,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_t03_chain(root: Path, *, complete: bool = True) -> None:
    case = root / "cases" / "100"
    _write_json(
        case / "step3_status.json",
        {
            "case_id": "100",
            "target_group_node_ids": ["100", "101"],
        },
    )
    _write_json(
        case / "step6_status.json",
        {
            "case_id": "100",
            "association_class": "B",
            "association_state": "not_established",
        },
    )
    _write_json(case / "step6_audit.json", {})
    _write_json(
        case / "step7_status.json",
        {"case_id": "100", "step7_state": "rejected"},
    )
    if complete:
        _write_json(case / "step7_audit.json", {})


def test_t03_rejected_formal_chain_and_t07_rows_are_loaded(
    tmp_path: Path,
) -> None:
    t03 = tmp_path / "t03"
    _write_t03_chain(t03)
    t07 = tmp_path / "t07"
    _write_json(
        t07 / "relation_cardinality_errors.json",
        {
            "run_id": "t07",
            "rows": [
                {
                    "error_type": "many_target_to_one_base",
                    "target_id": "100|101",
                    "base_id": "base",
                }
            ],
        },
    )

    sources = load_junction_sources(
        t03_run_root=t03,
        t07_step3_run_root=t07,
    )

    assert [case.case_id for case in sources.t03_cases] == ["100"]
    assert sources.t03_cases[0].association_status["association_class"] == "B"
    assert len(sources.t07_rows) == 1
    assert sources.audit["t03"]["artifact_count"] == 5
    assert sources.audit["silent_fix"] is False


def test_incomplete_t03_rejected_chain_is_blocked(tmp_path: Path) -> None:
    t03 = tmp_path / "t03"
    _write_t03_chain(t03, complete=False)

    with pytest.raises(T12ContractError, match="incomplete formal audit chains"):
        load_junction_sources(
            t03_run_root=t03,
            t07_step3_run_root=None,
        )
