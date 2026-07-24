from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_features import (
    forbidden_feature_hits,
    jsg_feature_tokens,
    roadgraph_feature_tokens,
    score_confidence,
    v0_cost,
    v0_weight_contract,
)


def test_jsg_features_do_not_include_object_identity() -> None:
    candidate = {
        "candidate_id": "candidate-secret",
        "case_key": "T10:case-secret",
        "object_key": "object-secret",
        "group_id": "PTO_A:JUNCTION:object-secret",
        "stage": "PTO_A",
        "object_type": "JUNCTION",
        "group_mode": "EXACTLY_ONE",
        "payload": {
            "junction_id": "object-secret",
            "junction_type": "NORMAL",
            "growth_level": "1",
            "state": "PUBLISHABLE",
        },
        "dependencies": [],
        "source_kinds": ["T01_INFERENCE_EVIDENCE"],
        "evidence_refs": [{"role": "t01_nodes", "object_id": "object-secret"}],
    }
    tokens = jsg_feature_tokens(candidate, group_option_count=3)
    assert not forbidden_feature_hits(tokens, candidate)
    assert all("secret" not in token for token in tokens)
    assert "payload:state=PUBLISHABLE" in tokens
    assert v0_cost(tokens) < 0


def test_roadgraph_features_use_source_role_not_paths_or_ids() -> None:
    candidate = {
        "candidate_id": "pto:secret",
        "business_id": "case-secret",
        "group_id": "FINAL_ROAD:BASE:road-secret",
        "base_object_id": "road-secret",
        "stage": "FINAL_ROAD",
        "object_kind": "Road",
        "action": "COPY",
        "lineage_kind": "base_identity",
        "group_mode": "EXACTLY_ONE",
        "output_payloads": [
            {
                "id": "road-secret",
                "geometry": {"type": "LineString", "coordinates": [[1, 2], [3, 4]]},
                "properties": {"source": 2, "snodeid": "node-secret"},
            }
        ],
        "sources": [
            {
                "source_kind": "BASE_IDENTITY",
                "role": "prepared_swsd_roads",
                "artifact_path": "secret/path.gpkg",
            }
        ],
    }
    tokens = roadgraph_feature_tokens(candidate, group_option_count=2)
    assert not forbidden_feature_hits(tokens, candidate)
    assert "source_role:prepared_swsd_roads" in tokens
    assert "property:source=2" in tokens
    assert all("road-secret" not in token and "node-secret" not in token for token in tokens)


def test_confidence_uses_group_margin() -> None:
    confidence, uncertainty, margin = score_confidence(-2.0, 0.0)
    assert margin == 2.0
    assert confidence > 0.5
    assert confidence + uncertainty == 1.0


def test_v0_weight_contract_is_explicit_and_has_zero_unknown_weight() -> None:
    contract = v0_weight_contract()
    assert contract["schema_version"] == "p05-jsg-p2-v0-explicit-model-v1"
    assert contract["unknown_feature_weight"] == 0.0
    assert contract["feature_weights"]["action:SPLIT"] == -0.25
