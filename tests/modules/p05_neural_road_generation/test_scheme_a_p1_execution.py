from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_execution import (
    _semantic_payload_signature,
    expand_movement_fallback_closure,
    fallback_conflicting_groups_to_swsd,
    materialize_case_roadgraph,
    select_effective_candidate,
)


def test_semantic_payload_signature_ignores_only_non_carrier_extension_fields() -> None:
    base = {
        "properties": {
            "id": 1,
            "kind": 4,
            "grade": 3,
            "mainnodeid": None,
        },
        "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
    }
    extension_only = {
        "properties": {
            "id": "1",
            "kind": 4,
            "grade": 3,
            "mainnodeid": None,
            "has_evd": "no",
            "semantic_junction_group_id": None,
        },
        "geometry": {"type": "Point", "coordinates": [10.0, 20.0, 0.0]},
    }
    topology_change = {
        **extension_only,
        "properties": {**extension_only["properties"], "mainnodeid": "99"},
    }
    geometry_change = {
        **extension_only,
        "geometry": {"type": "Point", "coordinates": [10.1, 20.0, 0.0]},
    }
    assert _semantic_payload_signature(base) == _semantic_payload_signature(extension_only)
    assert _semantic_payload_signature(base) != _semantic_payload_signature(topology_change)
    assert _semantic_payload_signature(base) != _semantic_payload_signature(geometry_change)


def _candidate(identifier: str, source: str, payload: list[str]) -> dict[str, object]:
    return {
        "candidate_id": identifier,
        "candidate_target": "KEEP_SWSD" if source == "SWSD_IDENTITY" else "USE_RCSD",
        "target_kind": "ROAD",
        "target_payload": payload,
        "source_kinds": [source],
    }


def test_scheme_a_p1_hard_gate_selects_swsd() -> None:
    candidates = [
        _candidate("strategy", "REGISTERED_STRATEGY_PROPOSAL", ["r2"]),
        _candidate("swsd", "SWSD_IDENTITY", ["r1"]),
    ]
    result = select_effective_candidate(
        candidates,
        selected_candidate_id="strategy",
        confidence=0.99,
        anomaly_probability=0.01,
        confidence_threshold=0.8,
        anomaly_threshold=0.5,
        hard_unsafe=True,
    )
    assert result["decision"] == "HARD_FALLBACK"
    assert result["effective_candidate_id"] == "swsd"


def test_shared_movement_fallback_expands_to_junction() -> None:
    group_candidates = {
        "m1": [
            {
                **_candidate("m1-s", "SWSD_IDENTITY", ["n1"]),
                "target_kind": "NODE",
            }
        ],
        "m2": [
            {
                **_candidate("m2-s", "SWSD_IDENTITY", ["n1"]),
                "target_kind": "NODE",
            }
        ],
    }
    rows = [
        {
            "group_id": "m1",
            "object_type": "MOVEMENT",
            "object_id": "j:a_b->b_c",
            "decision": "MODEL_FALLBACK",
            "selected_candidate_id": "m1-s",
            "effective_candidate_id": "m1-s",
        },
        {
            "group_id": "m2",
            "object_type": "MOVEMENT",
            "object_id": "j:b_c->c_d",
            "decision": "PUBLISH_CANDIDATE",
            "selected_candidate_id": "m2-s",
            "effective_candidate_id": "m2-s",
        },
    ]
    expanded = expand_movement_fallback_closure(rows, group_candidates)
    assert {row["fallback_unit"] for row in expanded} == {"JUNCTION"}
    assert all(row["decision"] != "PUBLISH_CANDIDATE" for row in expanded)


def test_segment_fallback_does_not_propagate_to_movement() -> None:
    group_candidates = {
        "s1": [_candidate("s1-s", "SWSD_IDENTITY", ["r1"])],
        "s2": [_candidate("s2-p", "REGISTERED_STRATEGY_PROPOSAL", ["r2"])],
        "m1": [
            {
                **_candidate("m1-s", "SWSD_IDENTITY", ["n1"]),
                "target_kind": "NODE",
            }
        ],
    }
    rows = [
        {
            "group_id": "s1",
            "object_type": "SEGMENT",
            "object_id": "a_b",
            "decision": "HARD_FALLBACK",
            "selected_candidate_id": "s1-s",
            "effective_candidate_id": "s1-s",
        },
        {
            "group_id": "s2",
            "object_type": "SEGMENT",
            "object_id": "c_d",
            "decision": "PUBLISH_CANDIDATE",
            "selected_candidate_id": "s2-p",
            "effective_candidate_id": "s2-p",
        },
        {
            "group_id": "m1",
            "object_type": "MOVEMENT",
            "object_id": "j:a_b->c_d",
            "decision": "PUBLISH_CANDIDATE",
            "selected_candidate_id": "m1-s",
            "effective_candidate_id": "m1-s",
        },
    ]
    expanded = expand_movement_fallback_closure(rows, group_candidates)
    by_group = {row["group_id"]: row for row in expanded}
    assert by_group["m1"]["decision"] == "PUBLISH_CANDIDATE"
    assert by_group["m1"]["fallback_unit"] == "MOVEMENT"
    assert by_group["s2"]["decision"] == "PUBLISH_CANDIDATE"


def test_conflict_fallback_does_not_expand_to_unrelated_segment() -> None:
    group_candidates = {
        "s1": [
            _candidate("s1-p", "REGISTERED_STRATEGY_PROPOSAL", ["p1"]),
            _candidate("s1-s", "SWSD_IDENTITY", ["s1"]),
        ],
        "s2": [
            _candidate("s2-p", "REGISTERED_STRATEGY_PROPOSAL", ["p2"]),
            _candidate("s2-s", "SWSD_IDENTITY", ["s2"]),
        ],
    }
    rows = [
        {
            "group_id": group_id,
            "object_type": "SEGMENT",
            "object_id": group_id,
            "decision": "PUBLISH_CANDIDATE",
            "selected_candidate_id": f"{group_id}-p",
            "effective_candidate_id": f"{group_id}-p",
        }
        for group_id in ("s1", "s2")
    ]
    resolved, changed = fallback_conflicting_groups_to_swsd(
        rows, group_candidates, ["s1"], reason="test_conflict"
    )
    by_group = {row["group_id"]: row for row in resolved}
    assert changed == 1
    assert by_group["s1"]["effective_candidate_id"] == "s1-s"
    assert by_group["s2"]["effective_candidate_id"] == "s2-p"


def test_materializer_attributes_node_conflict_to_both_groups(tmp_path: Path) -> None:
    proposal_roads = tmp_path / "proposal_roads.geojson"
    proposal_nodes = tmp_path / "proposal_nodes.geojson"
    t01_nodes = tmp_path / "t01_nodes.geojson"
    _write_geojson(
        proposal_roads,
        "LineString",
        [
            {
                "type": "Feature",
                "properties": {
                    "id": "r1",
                    "snodeid": "n1",
                    "enodeid": "n2",
                    "direction": "1",
                },
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
            }
        ],
    )
    _write_geojson(
        proposal_nodes,
        "Point",
        [
            _node_feature("n1", [0, 0]),
            _node_feature("n2", [1, 0]),
        ],
    )
    _write_geojson(t01_nodes, "Point", [_node_feature("n1", [0, 1])])
    candidates = {
        "road": {
            "candidate_id": "road",
            "target_kind": "ROAD",
            "target_payload": ["r1"],
            "source_kinds": ["REGISTERED_STRATEGY_PROPOSAL"],
            "payload_artifacts": [["proposal_roads", str(proposal_roads), "0"]],
            "payload_artifact_by_id": [
                ["r1", "proposal_roads", str(proposal_roads), "0"]
            ],
        },
        "node": {
            "candidate_id": "node",
            "target_kind": "NODE",
            "target_payload": ["n1"],
            "source_kinds": ["SWSD_IDENTITY"],
            "payload_artifacts": [["t01_nodes", str(t01_nodes), "0"]],
            "payload_artifact_by_id": [["n1", "t01_nodes", str(t01_nodes), "0"]],
        },
    }
    predictions = [
        {
            "group_id": "segment-group",
            "object_type": "SEGMENT",
            "object_id": "segment",
            "decision": "PUBLISH_CANDIDATE",
            "effective_candidate_id": "road",
            "effective_source_kind": "REGISTERED_STRATEGY_PROPOSAL",
        },
        {
            "group_id": "movement-group",
            "object_type": "MOVEMENT",
            "object_id": "j:a->b",
            "decision": "PUBLISH_CANDIDATE",
            "effective_candidate_id": "node",
            "effective_source_kind": "SWSD_IDENTITY",
        },
    ]
    result = materialize_case_roadgraph(
        "case",
        predictions,
        candidates,
        {"proposal_nodes": str(proposal_nodes), "t01_nodes": str(t01_nodes)},
    )
    assert not result["audit"]["legal"]
    assert result["audit"]["failure_group_ids"] == [
        "movement-group",
        "segment-group",
    ]


def _node_feature(identifier: str, coordinates: list[int]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"id": identifier},
        "geometry": {"type": "Point", "coordinates": coordinates},
    }


def _write_geojson(
    path: Path, geometry_type: str, features: list[dict[str, object]]
) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": geometry_type,
                "crs": {
                    "type": "name",
                    "properties": {"name": "urn:ogc:def:crs:EPSG::3857"},
                },
                "features": features,
            }
        ),
        encoding="utf-8",
    )
