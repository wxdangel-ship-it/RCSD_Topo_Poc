from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.outputs import REVIEW_INDEX_FIELDNAMES
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.rcsd_alignment import (
    RCSD_ALIGNMENT_AMBIGUOUS,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_ROAD_ONLY,
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_CONSISTENCY_RESULT_VALUES,
    ConsistencyVerdict,
    compute_consistency_verdict,
    validate_rcsd_consistency_result,
)


class _RoadOnlyChain:
    def __init__(self, consistent: bool) -> None:
        self.swsd_direction_consistent = consistent


def test_compute_consistency_verdict_truth_table() -> None:
    rows = [
        (
            RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            "A",
            False,
            None,
            ConsistencyVerdict.STRONG_CONSISTENT,
        ),
        (
            RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            "B",
            False,
            None,
            ConsistencyVerdict.PARTIAL_CONSISTENT,
        ),
        (
            RCSD_ALIGNMENT_JUNCTION_PARTIAL,
            "B",
            False,
            None,
            ConsistencyVerdict.PARTIAL_CONSISTENT,
        ),
        (
            RCSD_ALIGNMENT_ROAD_ONLY,
            "C",
            False,
            _RoadOnlyChain(True),
            ConsistencyVerdict.DIRECTION_ONLY_CONSISTENT,
        ),
        (
            RCSD_ALIGNMENT_ROAD_ONLY,
            "C",
            False,
            _RoadOnlyChain(False),
            ConsistencyVerdict.INCONSISTENT,
        ),
        (
            RCSD_ALIGNMENT_NONE,
            "C",
            False,
            None,
            ConsistencyVerdict.NOT_APPLICABLE,
        ),
        (
            RCSD_ALIGNMENT_AMBIGUOUS,
            "C",
            False,
            None,
            ConsistencyVerdict.BLOCKED,
        ),
        (
            RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            "A",
            True,
            None,
            ConsistencyVerdict.INCONSISTENT,
        ),
    ]

    for alignment_type, level, inverted, chain, expected in rows:
        assert (
            compute_consistency_verdict(
                rcsd_alignment_type=alignment_type,
                positive_rcsd_consistency_level=level,
                axis_polarity_inverted=inverted,
                rcsdroad_only_chain=chain,
            )
            == expected
        )


def test_rcsd_consistency_result_value_domain_is_frozen() -> None:
    assert RCSD_CONSISTENCY_RESULT_VALUES == (
        "positive_rcsd_strong_consistent",
        "positive_rcsd_partial_consistent",
        "positive_rcsd_direction_only_consistent",
        "positive_rcsd_inconsistent",
        "road_surface_fork_without_bound_target_rcsd",
        "missing_positive_rcsd",
        "none",
    )
    assert validate_rcsd_consistency_result("none") == "none"
    with pytest.raises(ValueError, match="outside frozen value domain"):
        validate_rcsd_consistency_result("swsd_junction_window_no_rcsd")


def test_review_index_field_order_matches_contract_addition() -> None:
    assert "swsd_rcsd_alignment_consistent" in REVIEW_INDEX_FIELDNAMES
    assert REVIEW_INDEX_FIELDNAMES.index("swsd_rcsd_alignment_consistent") == (
        REVIEW_INDEX_FIELDNAMES.index("rcsd_consistency_result") + 1
    )
