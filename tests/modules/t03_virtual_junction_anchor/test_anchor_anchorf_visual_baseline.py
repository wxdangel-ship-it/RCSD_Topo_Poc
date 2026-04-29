from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_association_case_specs,
    load_association_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    FinalizationContext,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_batch_runner import (
    run_t03_step3_legal_space_batch,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    build_step7_result,
)


BASELINE_PATH = (
    Path(__file__).with_name("data")
    / "t03_anchor_anchorf_visual_baseline_20260429.json"
)
DATASET_ROOTS = {
    "anchor": Path("/mnt/e/TestData/POC_Data/T02/Anchor"),
    "anchor_f": Path("/mnt/e/TestData/POC_Data/T02/Anchor_F"),
}


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _entries_by_dataset() -> dict[str, list[dict[str, Any]]]:
    entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in _load_baseline()["cases"]:
        entries[str(entry["dataset"])].append(entry)
    return entries


def _case_sort_key(entry: dict[str, Any]) -> tuple[int, int | str]:
    case_id = str(entry["case_id"])
    return (0, int(case_id)) if case_id.isdigit() else (1, case_id)


@pytest.fixture(scope="module")
def generated_step3_roots(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    missing_roots = [str(root) for root in DATASET_ROOTS.values() if not root.is_dir()]
    if missing_roots:
        pytest.skip(f"missing local visual baseline case roots: {missing_roots}")

    run_root = tmp_path_factory.mktemp("t03_anchor_anchorf_visual_baseline")
    step3_roots: dict[str, Path] = {}
    for dataset, entries in _entries_by_dataset().items():
        case_ids = [str(entry["case_id"]) for entry in sorted(entries, key=_case_sort_key)]
        step3_roots[dataset] = run_t03_step3_legal_space_batch(
            case_root=DATASET_ROOTS[dataset],
            case_ids=case_ids,
            out_root=run_root / "step3",
            run_id=f"{dataset}_step3_visual_baseline",
            workers=4,
            debug=False,
        )
    return step3_roots


def test_t03_anchor_anchorf_visual_baseline_manifest_counts() -> None:
    baseline = _load_baseline()
    cases = list(baseline["cases"])

    assert baseline["case_count"] == len(cases) == 65
    assert dict(Counter(entry["step7_state"] for entry in cases)) == baseline["step7_state_counts"]
    assert dict(Counter(entry["association_class"] for entry in cases)) == baseline["association_class_counts"]


@pytest.mark.parametrize(
    "entry",
    _load_baseline()["cases"],
    ids=lambda item: f"{item['dataset']}::{item['case_id']}",
)
def test_t03_anchor_anchorf_visual_baseline_case_state_and_abc_class(
    generated_step3_roots: dict[str, Path],
    entry: dict[str, Any],
) -> None:
    dataset = str(entry["dataset"])
    case_id = str(entry["case_id"])

    specs, _ = load_association_case_specs(
        case_root=DATASET_ROOTS[dataset],
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(
        case_spec=specs[0],
        step3_root=generated_step3_roots[dataset],
    )
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert association_case_result.template_class == entry["template_class"]
    assert association_case_result.association_class == entry["association_class"]
    assert association_case_result.association_state == entry["association_state"]
    assert step6_result.step6_state == entry["step6_state"]
    assert step7_result.step7_state == entry["step7_state"]
