from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_context import (
    build_context_tokens,
    describe_group,
    forbidden_context_hits,
    reverse_dependencies,
)


def _row(group_id: str, object_type: str, tokens: list[str]) -> dict:
    return {
        "case_key": "T10:case-secret",
        "domain": "JSG",
        "group_id": group_id,
        "object_type": object_type,
        "feature_tokens": tokens,
    }


def test_context_uses_dependency_semantics_without_identity() -> None:
    junction = describe_group(
        [
            _row(
                "PTO_A:JUNCTION:j-secret",
                "JUNCTION",
                ["object_type:JUNCTION", "payload:junction_type=NORMAL", "payload:state=REVIEW"],
            ),
            _row(
                "PTO_A:JUNCTION:j-secret",
                "JUNCTION",
                [
                    "object_type:JUNCTION",
                    "payload:junction_type=NORMAL",
                    "payload:state=PUBLISHABLE",
                ],
            ),
        ]
    )
    relation = describe_group(
        [
            _row(
                "PTO_A:RELATION:r-secret",
                "RELATION",
                ["object_type:RELATION", "payload:structural_role=THROUGH", "payload:state=REVIEW"],
            ),
            _row(
                "PTO_A:RELATION:r-secret",
                "RELATION",
                [
                    "object_type:RELATION",
                    "payload:structural_role=THROUGH",
                    "payload:state=PUBLISHABLE",
                ],
            ),
        ],
        dependencies=[junction.group_id],
    )
    descriptors = {
        (junction.case_key, junction.domain, junction.group_id): junction,
        (relation.case_key, relation.domain, relation.group_id): relation,
    }
    reverse = reverse_dependencies(descriptors)
    tokens = build_context_tokens(
        relation,
        descriptors=descriptors,
        reverse_map=reverse,
        case_type_counts={(relation.case_key, "JSG"): {"JUNCTION": 1, "RELATION": 1}},
    )
    assert "ctx:dependency:JUNCTION:payload:junction_type=NORMAL" in tokens
    assert not forbidden_context_hits(
        tokens, identifiers=["case-secret", "j-secret", "r-secret"]
    )


def test_context_audit_rejects_identity_and_truth_markers() -> None:
    assert forbidden_context_hits(
        ["ctx:case_key=secret", "ctx:truth=true", "ctx:self_type=JUNCTION"]
    ) == ["ctx:case_key=secret", "ctx:truth=true"]


def test_context_includes_relative_structure_without_join_identity() -> None:
    relation = describe_group(
        [
            _row(
                "PTO_A:RELATION:r-secret",
                "RELATION",
                ["object_type:RELATION", "payload:direction_role=ENTER"],
            ),
            _row(
                "PTO_A:RELATION:r-secret",
                "RELATION",
                ["object_type:RELATION", "payload:direction_role=EXIT"],
            ),
        ]
    )
    key = (relation.case_key, relation.domain, relation.group_id)

    tokens = build_context_tokens(
        relation,
        descriptors={key: relation},
        reverse_map={},
        case_type_counts={(relation.case_key, "JSG"): {"RELATION": 1}},
        structural_tokens={key: ("relation_access_position=START",)},
    )

    assert "ctx:self_structure:relation_access_position=START" in tokens
    assert not forbidden_context_hits(tokens, identifiers=["case-secret", "r-secret"])
