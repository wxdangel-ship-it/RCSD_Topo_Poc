from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.segment_construction_audit import (
    _anchor_statuses,
    _failed_nodes_by_segment,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_replacement_models import (
    JunctionState,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_replacement_relation_support import (
    _assign_added_rcsd_nodes_to_junction_states,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_semantic_junction_groups import (
    _build_relation_context_index,
    _relation_context,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_support import (
    _DirectedRoadGraph,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_surface_topology_support


def _feature(**properties: object) -> dict[str, object]:
    return {"type": "Feature", "properties": properties, "geometry": None}


def test_added_rcsd_nodes_use_semantic_and_segment_intersection_without_changing_order() -> None:
    junctions = {
        "c1": JunctionState(
            c_id="c1",
            replacement_segment_ids=["s1", "s2"],
            mapped_rcsd_semantic_ids=["semantic-a"],
        ),
        "c2": JunctionState(
            c_id="c2",
            replacement_segment_ids=["s2"],
            mapped_rcsd_semantic_ids=["semantic-a", "semantic-b"],
        ),
        "c3": JunctionState(
            c_id="c3",
            replacement_segment_ids=["s3"],
            mapped_rcsd_semantic_ids=["semantic-a"],
        ),
    }
    canonicalizer = NodeCanonicalizer(
        aliases={"raw-a1": "semantic-a", "raw-a2": "semantic-a"},
        semantic_node_ids=frozenset({"semantic-a", "semantic-b"}),
    )

    _assign_added_rcsd_nodes_to_junction_states(
        junctions=junctions,
        rcsd_nodes=[
            _feature(id="ignored"),
            _feature(id="raw-a1"),
            _feature(id="raw-a2"),
        ],
        added_node_to_segments={
            "raw-a1": ["s2"],
            "raw-a2": ["s3"],
        },
        canonicalizer=canonicalizer,
    )

    assert junctions["c1"].added_rcsd_node_ids == ["raw-a1"]
    assert junctions["c2"].added_rcsd_node_ids == ["raw-a1"]
    assert junctions["c3"].added_rcsd_node_ids == ["raw-a2"]


def test_relation_context_index_preserves_original_row_order_and_unique_order() -> None:
    rows = [
        _feature(swsd_segment_id="s2", relation_status="mixed", source_mix="1+2"),
        _feature(swsd_segment_id="s1", relation_status="replaced", source_mix="1"),
        _feature(swsd_segment_id="s2", relation_status="replaced", source_mix="1"),
        _feature(swsd_segment_id="s3", relation_status="retained", source_mix="2"),
    ]

    index = _build_relation_context_index(rows)

    assert _relation_context(index, ["s1", "s2", "s1"]) == (
        ["mixed", "replaced"],
        ["1+2", "1"],
    )
    assert _relation_context(index, []) == ([], [])


def test_failed_node_index_keeps_anchor_status_semantics() -> None:
    failed_nodes = _failed_nodes_by_segment(
        [
            _feature(
                swsd_segment_id="s1",
                failed_node_ids=["n1"],
                failed_pair_nodes=["p1"],
            ),
            _feature(
                swsd_segment_id="s1",
                failed_junc_nodes=["j1"],
            ),
            _feature(
                swsd_segment_id="s2",
                failed_pair_nodes=["p2"],
            ),
        ]
    )

    assert failed_nodes == {"s1": {"n1", "p1", "j1"}, "s2": {"p2"}}
    assert _anchor_statuses(
        is_replaceable=False,
        pair_nodes={"p1"},
        junc_nodes={"j1"},
        step1_reasons=[],
        step2_reasons=[],
        failed_nodes=failed_nodes["s1"],
    ) == ("incomplete", "not_evaluated")


def test_undirected_reachability_uses_graph_component_semantics() -> None:
    graph = _DirectedRoadGraph(
        [
            _feature(id="r1", snodeid="a", enodeid="b", direction=2),
            _feature(id="r2", snodeid="b", enodeid="c", direction=2),
            _feature(id="r3", snodeid="x", enodeid="y", direction=2),
        ],
        canonicalizer=NodeCanonicalizer(aliases={}, semantic_node_ids=frozenset()),
    )

    assert graph.undirected_reachable_any(["a"], ["c"])
    assert graph.undirected_reachable_any(["c"], ["a"])
    assert not graph.undirected_reachable_any(["a"], ["x"])
    assert graph.reachable_any(["a"], ["c"])
    assert not graph.reachable_any(["c"], ["a"])


def test_surface_invariant_context_reuses_immutable_inputs(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "replacement_plan.csv"
    source_path.write_text("placeholder", encoding="utf-8")
    calls = {"surfaces": 0, "rejects": 0, "step2": 0}

    def load_surfaces(**_kwargs):
        calls["surfaces"] += 1
        return {"t05": object()}

    def load_rejects(_path):
        calls["rejects"] += 1
        return {"n1": [{"reject_reason": "r1"}]}

    def read_step2(_path):
        calls["step2"] += 1
        return [
            {
                "swsd_segment_id": "s1",
                "optional_junc_nodes": "n1",
                "optional_junc_rcsd_nodes": "r1",
                "dropped_junc_nodes": "n2",
            }
        ]

    monkeypatch.setattr(step3_surface_topology_support, "_load_surfaces", load_surfaces)
    monkeypatch.setattr(step3_surface_topology_support, "_load_t04_rejects", load_rejects)
    monkeypatch.setattr(step3_surface_topology_support, "_read_step2_junc_rows", read_step2)
    monkeypatch.setattr(
        step3_surface_topology_support,
        "_step2_junc_source_path",
        lambda _root: source_path,
    )

    class Cache(dict):
        pass

    cache = Cache()
    kwargs = {
        "step_root": tmp_path / "validation-a",
        "t07_surface_path": None,
        "t03_surface_path": None,
        "t04_surface_path": None,
        "t04_audit_path": None,
        "t05_surface_path": None,
        "cache": cache,
    }
    first = step3_surface_topology_support.load_surface_topology_invariant_context(**kwargs)
    second = step3_surface_topology_support.load_surface_topology_invariant_context(
        **{**kwargs, "step_root": tmp_path / "validation-b"}
    )

    assert second is first
    assert calls == {"surfaces": 1, "rejects": 1, "step2": 1}
    assert first.step2_junc_mappings == {("s1", "n1"): ["r1"]}
    assert first.step2_dropped_junc_nodes == {"s1": ["n2"]}
