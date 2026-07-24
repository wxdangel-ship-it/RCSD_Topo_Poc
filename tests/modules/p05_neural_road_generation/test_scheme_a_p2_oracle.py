from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_execution import (
    materialize_case_roadgraph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_oracle import (
    candidate_intrinsic_reasons,
    choose_common_node_options,
)


def test_candidate_intrinsic_reasons_do_not_treat_junction_conflict_as_segment_unsafe() -> None:
    assert candidate_intrinsic_reasons(
        ["JUNCTION_CARRIER_CONFLICT:True"],
        ["SWSD_IDENTITY"],
        anomaly_target=False,
        truth_target="KEEP_SWSD",
    ) == []


def test_candidate_intrinsic_reasons_reject_proposal_missing_access() -> None:
    assert candidate_intrinsic_reasons(
        ["PROPOSAL_ACCESS_MISSING_COUNT:2"],
        ["REGISTERED_STRATEGY_PROPOSAL"],
        anomaly_target=False,
        truth_target="USE_RCSD",
    ) == ["proposal_access_missing"]


def test_choose_common_node_options_selects_shared_mainnode_and_truth_payload() -> None:
    options = {
        "n1": [
            _node_option("n1-swsd", "n1", "t01_nodes", "swsd-1"),
            _node_option("n1-proposal", "j1", "proposal_nodes", "truth-1"),
        ],
        "n2": [
            _node_option("n2-swsd", "n2", "t01_nodes", "swsd-2"),
            _node_option("n2-proposal", "j1", "proposal_nodes", "truth-2"),
        ],
    }
    key, selected, reason = choose_common_node_options(
        ["n1", "n2"],
        options,
        {"n1": "truth-1", "n2": "truth-2"},
        junction_id="j1",
    )
    assert reason == ""
    assert key == "j1"
    assert {node_id: row["candidate_id"] for node_id, row in selected.items()} == {
        "n1": "n1-proposal",
        "n2": "n2-proposal",
    }


def test_choose_common_node_options_reports_no_shared_mainnode() -> None:
    options = {
        "n1": [_node_option("n1", "a", "t01_nodes", "s1")],
        "n2": [_node_option("n2", "b", "t01_nodes", "s2")],
    }
    key, selected, reason = choose_common_node_options(
        ["n1", "n2"], options, {}, junction_id="j1"
    )
    assert key == ""
    assert selected == {}
    assert reason == "no_common_mainnode_key"


def test_materializer_accepts_explicit_node_carrier_override(tmp_path: Path) -> None:
    roads = tmp_path / "proposal_roads.geojson"
    nodes = tmp_path / "proposal_nodes.geojson"
    _write_geojson(
        roads,
        [
            {
                "type": "Feature",
                "properties": {
                    "id": "r1",
                    "snodeid": "n1",
                    "enodeid": "n2",
                    "direction": "1",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0, 0], [1, 0]],
                },
            }
        ],
    )
    _write_geojson(nodes, [_node("n1", [0, 0]), _node("n2", [1, 0])])
    candidates = {
        "road": {
            "candidate_id": "road",
            "target_kind": "ROAD",
            "target_payload": ["r1"],
            "source_kinds": ["REGISTERED_STRATEGY_PROPOSAL"],
            "payload_artifacts": [["proposal_roads", str(roads), "sha"]],
            "payload_artifact_by_id": [
                ["r1", "proposal_roads", str(roads), "sha"]
            ],
        }
    }
    predictions = [
        {
            "group_id": "segment",
            "object_type": "SEGMENT",
            "object_id": "segment",
            "decision": "PUBLISH_CANDIDATE",
            "effective_candidate_id": "road",
            "effective_source_kind": "REGISTERED_STRATEGY_PROPOSAL",
        }
    ]
    override = _node("n1", [0, 1])
    result = materialize_case_roadgraph(
        "case",
        predictions,
        candidates,
        {"proposal_nodes": str(nodes)},
        node_payload_overrides={"n1": override},
        node_source_overrides={"n1": "t01_nodes"},
    )
    assert result["audit"]["legal"]
    assert result["audit"]["explicit_node_carrier_override_count"] == 1
    assert result["node_sources"]["n1"] == ["t01_nodes"]
    assert result["node_sources"]["n2"] == ["proposal_nodes"]


def _node_option(
    candidate_id: str, mainnode_key: str, source_role: str, signature: str
) -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "mainnode_key": mainnode_key,
        "source_role": source_role,
        "semantic_signature": signature,
    }


def _node(identifier: str, coordinates: list[int]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"id": identifier, "mainnodeid": None},
        "geometry": {"type": "Point", "coordinates": coordinates},
    }


def _write_geojson(path: Path, features: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "urn:ogc:def:crs:EPSG::3857"},
                },
                "features": features,
            }
        ),
        encoding="utf-8",
    )
