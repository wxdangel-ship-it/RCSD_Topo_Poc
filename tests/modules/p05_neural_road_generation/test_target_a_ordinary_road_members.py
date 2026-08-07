from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    _target_road_ids,
    _teacher_anchor_members,
    normalize_complete_target_ids,
    ordinary_anchor_role_features,
    ordinary_road_business_role_targets,
    selected_anchor_relation,
)


def test_complete_target_ids_normalize_split_roads_to_raw_source() -> None:
    values = normalize_complete_target_ids(
        ["final-1", "raw-2"],
        final_normalization={"final-1": "raw-1"},
    )
    assert values == {"raw-1", "raw-2"}


def test_selected_anchor_relation_keeps_anchor_and_road_separate() -> None:
    values = selected_anchor_relation(
        road_id="r2",
        start_node_id="n1",
        end_node_id="n2",
        selected_road_ids={"r1"},
        selected_node_ids={"n2"},
    )
    assert values == [0.0, 0.0, 1.0, 1.0]


def test_teacher_forcing_uses_one_preferred_anchor_candidate() -> None:
    result = _teacher_anchor_members(
        "case",
        ("anchor",),
        {
            ("case", "anchor"): {
                "sample_id": "sample",
                "candidate_ids": ["ROAD:r1", "ROAD:r2"],
            }
        },
        {
            "sample": {
                "candidate_acceptable_indices": [0, 1],
                "preferred_candidate_index": 1,
                "status_label": 0,
            }
        },
    )
    assert result["road_ids"] == {"r2"}
    assert result["node_ids"] == set()
    assert result["selections"] == (({"r2"}, set()),)
    assert result["ready"]


def test_anchor_roles_keep_source_target_and_internal_identity() -> None:
    values = ordinary_anchor_role_features(
        ("source", "internal", "target"),
        ("source", "target"),
    )
    assert values == [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
    ]


def test_road_business_targets_separate_owner_and_connectivity() -> None:
    values = ordinary_road_business_role_targets(
        [
            {"road_id": "owner"},
            {"road_id": "connectivity"},
            {"road_id": "other"},
        ],
        target_ids={"owner"},
        target_state="USE_RCSD_NORMALIZED_RAW",
        relation={
            "related_connectivity_road_ids": "['connectivity']",
            "related_special_junction_internal_road_ids": "[]",
        },
        candidate_plans=[
            {
                "decision": "USE_RCSD",
                "road_ids": ["owner"],
                "road_roles": [
                    {"road_id": "owner", "role": "INTERNAL_CONNECTOR"}
                ],
            }
        ],
        final_normalization={},
    )
    assert values["ownership_targets"] == [1, 2, 0]
    assert values["business_role_targets"] == [2, 0, 0]
    assert values["ownership_task_mask"] == [True, True, True]
    assert values["business_role_task_mask"] == [True, True, True]


def test_t06_mixed_target_keeps_rcsd_and_attached_swsd_roads() -> None:
    target_ids, target_state = _target_road_ids(
        {
            "preferred_carrier_target": "T06_MAIN_RCSD_ATTACHED_SWSD",
            "acceptable_complete_road_targets": [
                {
                    "decision": "T06_MAIN_RCSD_ATTACHED_SWSD",
                    "road_ids": [
                        "raw-main",
                        "raw-connector",
                        "swsd-attached",
                        "generated-final",
                    ],
                }
            ],
        },
        segment={"swsd_road_ids": ["swsd-attached"]},
        raw_road_ids={"raw-main", "raw-connector"},
        swsd_road_ids={"swsd-attached"},
        final_normalization={},
    )
    assert target_ids == {
        "raw-main",
        "raw-connector",
        "swsd-attached",
        "generated-final",
    }
    assert target_state == "T06_MAIN_RCSD_ATTACHED_SWSD"


def test_t06_mixed_business_roles_separate_attached_swsd() -> None:
    values = ordinary_road_business_role_targets(
        [
            {"road_id": "raw-main", "source": "RCSD"},
            {"road_id": "raw-connector", "source": "RCSD"},
            {"road_id": "swsd-attached", "source": "SWSD"},
            {"road_id": "other", "source": "RCSD"},
        ],
        target_ids={"raw-main", "raw-connector", "swsd-attached"},
        target_state="T06_MAIN_RCSD_ATTACHED_SWSD",
        relation=None,
        candidate_plans=[
            {
                "decision": "USE_RCSD",
                "road_ids": ["raw-main", "raw-connector"],
                "road_roles": [
                    {"road_id": "raw-main", "role": "MAIN"},
                    {
                        "road_id": "raw-connector",
                        "role": "INTERNAL_CONNECTOR",
                    },
                ],
            }
        ],
        final_normalization={},
    )
    assert values["ownership_targets"] == [1, 1, 1, 0]
    assert values["business_role_targets"] == [1, 2, 3, 0]
    assert values["ownership_task_mask"] == [True, True, True, True]
    assert values["business_role_task_mask"] == [True, True, True, True]


def test_user_road_role_adjudication_overrides_only_confirmed_roads() -> None:
    values = ordinary_road_business_role_targets(
        [
            {"road_id": "5391352334583582", "source": "RCSD"},
            {"road_id": "5391352334583612", "source": "RCSD"},
            {"road_id": "5391352334583619", "source": "RCSD"},
            {"road_id": "unreviewed", "source": "RCSD"},
        ],
        case_key="T10:706247",
        segment_id="708001_708003",
        target_ids={
            "5391352334583582",
            "5391352334583612",
            "5391352334583619",
        },
        target_state="USE_RCSD_NORMALIZED_RAW",
        relation=None,
        candidate_plans=(),
        final_normalization={},
    )
    assert values["ownership_targets"] == [1, 1, 1, 0]
    assert values["business_role_targets"] == [1, 2, 1, 0]
    assert values["ownership_task_mask"] == [True, True, True, False]
    assert values["business_role_task_mask"] == [True, True, True, False]
    assert values["manual_adjudication_weight"] == 1.0
    assert values["manual_adjudication_count"] == 3


def test_user_road_membership_adjudication_only_promotes_ownership() -> None:
    values = ordinary_road_business_role_targets(
        [
            {"road_id": "5395379941867683", "source": "RCSD"},
            {"road_id": "5395379941867708", "source": "RCSD"},
            {"road_id": "unreviewed", "source": "RCSD"},
        ],
        case_key="T10:706247",
        segment_id="706285_706290",
        target_ids={"5395379941867683", "5395379941867708"},
        target_state="USE_RCSD_NORMALIZED_RAW",
        relation=None,
        candidate_plans=[
            {
                "decision": "USE_RCSD",
                "road_ids": ["5395379941867708"],
                "road_roles": [
                    {"road_id": "5395379941867708", "role": "MAIN"}
                ],
            }
        ],
        final_normalization={},
    )
    assert values["ownership_targets"] == [1, 1, 0]
    assert values["ownership_task_mask"] == [True, False, False]
    assert values["business_role_task_mask"] == [False, False, True]
    assert values["manual_ownership_adjudication_weight"] == 1.0
    assert values["manual_role_adjudication_weight"] == 0.0
    assert values["manual_adjudication_count"] == 1
    assert values["manual_ownership_adjudication_count"] == 1
    assert values["manual_role_adjudication_count"] == 0
