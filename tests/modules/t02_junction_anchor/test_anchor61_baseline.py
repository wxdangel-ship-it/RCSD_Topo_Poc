from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    run_t02_virtual_intersection_poc,
)

MANIFEST_PATH = Path(__file__).with_name("data") / "anchor61_manifest.json"


def _load_anchor61_manifest() -> list[dict[str, object]]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _case_inputs(case_root: Path) -> dict[str, Path]:
    return {
        "nodes_path": case_root / "nodes.gpkg",
        "roads_path": case_root / "roads.gpkg",
        "drivezone_path": case_root / "drivezone.gpkg",
        "rcsdroad_path": case_root / "rcsdroad.gpkg",
        "rcsdnode_path": case_root / "rcsdnode.gpkg",
    }


def _assert_tri_state_mapping(status_doc: dict[str, object]) -> None:
    acceptance_class = status_doc["acceptance_class"]
    business_outcome_class = status_doc["business_outcome_class"]
    visual_review_class = str(status_doc["visual_review_class"])

    if acceptance_class == "accepted":
        assert business_outcome_class == "success"
        assert visual_review_class.startswith("V1")
        return
    if acceptance_class == "review_required":
        assert business_outcome_class == "risk"
        assert visual_review_class.startswith("V2")
        return
    if acceptance_class == "rejected":
        assert business_outcome_class == "failure"
        assert visual_review_class.startswith(("V3", "V4", "V5"))
        return
    raise AssertionError(f"unexpected acceptance_class: {acceptance_class!r}")


@pytest.mark.parametrize(
    "entry",
    _load_anchor61_manifest(),
    ids=lambda item: str(item["case_id"]),
)
def test_anchor61_case_package_baseline(
    tmp_path: Path,
    entry: dict[str, object],
) -> None:
    case_id = str(entry["case_id"])
    case_root = normalize_runtime_path(str(entry["input_root"]))
    assert case_root.exists(), f"missing Anchor61 case root: {case_root}"

    render_root = tmp_path / "renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid=str(entry["mainnodeid"]),
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **_case_inputs(case_root),
    )
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))

    assert status_doc["mainnodeid"] == case_id
    assert bool(status_doc["official_review_eligible"]) is bool(entry["official_review_eligible"])
    _assert_tri_state_mapping(status_doc)

    if bool(entry["official_review_eligible"]):
        assert bool(status_doc["flow_success"]) is True
    else:
        assert status_doc["acceptance_class"] == "rejected"
        assert status_doc["business_outcome_class"] == "failure"

    if status_doc.get("kind") is not None:
        assert status_doc.get("kind_source") in {"nodes.kind", "nodes.kind_2"}

    assert artifacts.status_path.exists()
    assert artifacts.audit_json_path.exists()
    assert artifacts.virtual_polygon_path.exists()
    assert artifacts.rendered_map_path.exists()
