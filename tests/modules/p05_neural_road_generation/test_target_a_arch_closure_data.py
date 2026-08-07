from __future__ import annotations

from types import SimpleNamespace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureJunctionCacheEntry,
    _segment_anchor_state,
    build_arch_closure_reference_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)


def test_reference_store_context_stops_at_shared_required_junction() -> None:
    anchors = {
        "a": SimpleNamespace(
            case_key="T10:1", anchor_id="a", dependency_anchor_ids=("a", "c")
        ),
        "b": SimpleNamespace(
            case_key="T10:1", anchor_id="b", dependency_anchor_ids=("b",)
        ),
        "c": SimpleNamespace(
            case_key="T10:1", anchor_id="c", dependency_anchor_ids=("c", "a")
        ),
    }
    segments = {
        "s1": SimpleNamespace(
            segment_id="s1", required_anchor_ids=("a",), fold=1
        ),
        "s2": SimpleNamespace(
            segment_id="s2", required_anchor_ids=("a", "b"), fold=1
        ),
        "s3": SimpleNamespace(
            segment_id="s3", required_anchor_ids=("c",), fold=1
        ),
    }
    examples = []
    for segment_id, segment in segments.items():
        examples.append(
            SimpleNamespace(
                joint=SimpleNamespace(
                    case_key="T10:1",
                    ordinary_segments=(segment,),
                    anchors=tuple(anchors.values()),
                ),
                ledger={"segment_id": segment_id},
                road_pool=SimpleNamespace(segment_id=segment_id),
                access_features_by_junction={},
                break_tasks=(),
            )
        )

    stores = build_arch_closure_reference_stores(examples)

    assert stores.segments[("T10:1", "s1")].context_segment_keys == (
        ("T10:1", "s2"),
    )
    assert ("T10:1", "s3") not in stores.segments[
        ("T10:1", "s1")
    ].context_segment_keys
    assert stores.junctions[("T10:1", "a")].direct_segment_keys == (
        ("T10:1", "s1"),
        ("T10:1", "s2"),
    )


def test_segment_anchor_state_uses_only_locked_junction_results() -> None:
    cache = {
        ("T10:1", "a"): ArchClosureJunctionCacheEntry(
            key=("T10:1", "a"),
            business_state=ORDINARY_ANCHOR_SUCCESS,
            candidate_id="ROAD:r1",
            embedding=torch.zeros(8),
            confidence_values=torch.ones(4),
        ),
        ("T10:1", "b"): ArchClosureJunctionCacheEntry(
            key=("T10:1", "b"),
            business_state=ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
            candidate_id="",
            embedding=torch.zeros(8),
            confidence_values=torch.ones(4),
        ),
        ("T10:1", "c"): ArchClosureJunctionCacheEntry(
            key=("T10:1", "c"),
            business_state=ORDINARY_ANCHOR_UNRESOLVED,
            candidate_id="",
            embedding=torch.zeros(8),
            confidence_values=torch.ones(4),
        ),
    }

    assert _segment_anchor_state(
        (("T10:1", "a"),), junction_cache=cache
    ) == (ORDINARY_ANCHOR_SUCCESS, ("ROAD:r1",))
    assert _segment_anchor_state(
        (("T10:1", "a"), ("T10:1", "b")), junction_cache=cache
    ) == (ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE, ())
    assert _segment_anchor_state(
        (("T10:1", "a"), ("T10:1", "c")), junction_cache=cache
    ) == (ORDINARY_ANCHOR_UNRESOLVED, ())
