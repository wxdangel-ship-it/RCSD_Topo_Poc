from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessDirectionRole,
    SourceNodeRecord,
    SourceRoadRecord,
    materialize_target_a_roadgraph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer_audit import (
    build_t01_fallback_materialization_instructions,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    RoadSource,
)


def _road(
    road_id: str,
    start: str,
    end: str,
    coordinates: list[tuple[float, float]],
    *,
    direction: int = 2,
) -> SourceRoadRecord:
    return SourceRoadRecord(
        source_kind=RoadSource.SWSD,
        source_road_id=road_id,
        geometry=LineString(coordinates),
        start_node_id=start,
        end_node_id=end,
        direction=direction,
        crs="EPSG:3857",
        properties={"id": road_id},
    )


def _node(
    node_id: str,
    x: float,
    *,
    mainnodeid: str = "",
    subnodeid: str = "",
) -> SourceNodeRecord:
    return SourceNodeRecord(
        source_kind=RoadSource.SWSD,
        source_node_id=node_id,
        geometry=Point(x, 0),
        crs="EPSG:3857",
        properties={
            "id": node_id,
            "mainnodeid": mainnodeid,
            "subnodeid": subnodeid,
        },
    )


def _standard(
    segment_id: str,
    pair_nodes: tuple[str, str],
    road_ids: tuple[str, ...],
    *,
    independent_road_valid: bool = True,
    access_valid: bool = True,
) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "segment_type": "STANDARD",
        "pair_nodes": list(pair_nodes),
        "junc_nodes": [],
        "swsd_road_ids": list(road_ids),
        "independent_road_valid": independent_road_valid,
        "access_valid": access_valid,
        "source_segment_access": "",
        "target_segment_access": "",
    }


def _advance_right(
    segment_id: str,
    road_ids: tuple[str, ...],
    source_access: str,
    target_access: str,
    *,
    independent_road_valid: bool = True,
    access_valid: bool = True,
) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "segment_type": "ADVANCE_RIGHT",
        "pair_nodes": [],
        "junc_nodes": [],
        "swsd_road_ids": list(road_ids),
        "independent_road_valid": independent_road_valid,
        "access_valid": access_valid,
        "source_segment_access": source_access,
        "target_segment_access": target_access,
    }


def test_builds_complete_t01_fallback_ledger_with_advance_right() -> None:
    roads = {
        (RoadSource.SWSD, "left-road"): _road(
            "left-road", "n0", "n1", [(0, 0), (10, 0)]
        ),
        (RoadSource.SWSD, "right-road"): _road(
            "right-road", "n2", "n3", [(20, 0), (30, 0)]
        ),
        (RoadSource.SWSD, "ar-road"): _road(
            "ar-road", "n1", "n2", [(10, 0), (20, 0)]
        ),
    }
    nodes = {
        (RoadSource.SWSD, node_id): _node(node_id, x)
        for node_id, x in (("n0", 0), ("n1", 10), ("n2", 20), ("n3", 30))
    }
    skeleton = {
        "segments": [
            _standard("left", ("n0", "n1"), ("left-road",)),
            _standard("right", ("n2", "n3"), ("right-road",)),
            _advance_right(
                "ar",
                ("ar-road",),
                "left@n1",
                "right@n2",
            ),
        ]
    }
    plans, contracts, blockers = build_t01_fallback_materialization_instructions(
        skeleton,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert blockers == ()
    assert {row.segment_id for row in plans} == {"left", "right", "ar"}
    ar_plan = next(row for row in plans if row.segment_id == "ar")
    assert len(ar_plan.attachments) == 2
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right", "ar"),
        frozen_access_contracts=contracts,
        segment_instructions=plans,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert len(graph.roads) == 3
    assert graph.fallback_segment_ids == ("ar", "left", "right")
    assert graph.positive_keep_segment_ids == ()
    assert not graph.silent_fix
    assert not graph.content_repair


def test_invalid_advance_right_is_blocked_without_expanding_to_adjacent_segments() -> None:
    roads = {
        (RoadSource.SWSD, "left-road"): _road(
            "left-road", "n0", "n1", [(0, 0), (10, 0)]
        ),
        (RoadSource.SWSD, "right-road"): _road(
            "right-road", "n2", "n3", [(20, 0), (30, 0)]
        ),
        (RoadSource.SWSD, "ar-road"): _road(
            "ar-road", "n1", "n2", [(10, 0), (20, 0)]
        ),
    }
    nodes = {
        (RoadSource.SWSD, node_id): _node(node_id, x)
        for node_id, x in (("n0", 0), ("n1", 10), ("n2", 20), ("n3", 30))
    }
    skeleton = {
        "segments": [
            _standard("left", ("n0", "n1"), ("left-road",)),
            _standard("right", ("n2", "n3"), ("right-road",)),
            _advance_right(
                "ar",
                ("ar-road",),
                "",
                "",
                access_valid=False,
            ),
        ]
    }
    plans, contracts, blockers = build_t01_fallback_materialization_instructions(
        skeleton,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert {row.segment_id for row in plans} == {"left", "right"}
    assert [(row.segment_id, row.code) for row in blockers] == [
        ("ar", "FROZEN_ACCESS_INVALID")
    ]
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right"),
        frozen_access_contracts=contracts,
        segment_instructions=plans,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert graph.fallback_segment_ids == ("left", "right")


def test_ordinary_access_preserves_all_directional_roads_and_nodes() -> None:
    roads = {
        (RoadSource.SWSD, "a"): _road("a", "n0", "n1", [(0, 0), (5, 0)]),
        (RoadSource.SWSD, "b"): _road("b", "n0", "n2", [(0, 0), (5, 1)]),
    }
    nodes = {
        (RoadSource.SWSD, "n0"): _node("n0", 0),
        (RoadSource.SWSD, "n1"): _node("n1", 5),
        (RoadSource.SWSD, "n2"): SourceNodeRecord(
            source_kind=RoadSource.SWSD,
            source_node_id="n2",
            geometry=Point(5, 1),
            crs="EPSG:3857",
            properties={"id": "n2"},
        ),
    }
    plans, contracts, blockers = build_t01_fallback_materialization_instructions(
        {
            "segments": [
                _standard("ordinary", ("n0", "n1"), ("a", "b")),
            ]
        },
        source_roads=roads,
        source_nodes=nodes,
    )
    assert blockers == ()
    assert len(plans) == 1
    source_binding = next(
        binding
        for binding in plans[0].access_bindings
        if binding.access_node_id == "n0"
    )
    assert source_binding.road_instruction_ids == (
        "swsd:ordinary:a",
        "swsd:ordinary:b",
    )
    assert source_binding.direction_role is AccessDirectionRole.EXIT
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("ordinary",),
        frozen_access_contracts=contracts,
        segment_instructions=plans,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert graph.access_bindings["ordinary@n0"].road_ids == ("a", "b")


def test_mainnode_closure_is_used_only_inside_declared_segment_access() -> None:
    roads = {
        (RoadSource.SWSD, "left-road"): _road(
            "left-road", "n0", "sub", [(0, 0), (10, 0)]
        ),
        (RoadSource.SWSD, "right-road"): _road(
            "right-road", "n2", "n3", [(20, 0), (30, 0)]
        ),
        (RoadSource.SWSD, "ar-road"): _road(
            "ar-road", "main", "n2", [(10, 0), (20, 0)]
        ),
    }
    nodes = {
        (RoadSource.SWSD, "n0"): _node("n0", 0),
        (RoadSource.SWSD, "sub"): _node("sub", 10, mainnodeid="main"),
        (RoadSource.SWSD, "main"): _node("main", 10, subnodeid="sub"),
        (RoadSource.SWSD, "n2"): _node("n2", 20),
        (RoadSource.SWSD, "n3"): _node("n3", 30),
    }
    skeleton = {
        "segments": [
            _standard("left", ("n0", "main"), ("left-road",)),
            _standard("right", ("n2", "n3"), ("right-road",)),
            _advance_right(
                "ar",
                ("ar-road",),
                "left@main",
                "right@n2",
            ),
        ]
    }
    plans, contracts, blockers = build_t01_fallback_materialization_instructions(
        skeleton,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert blockers == ()
    assert {row.segment_id for row in plans} == {"left", "right", "ar"}
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right", "ar"),
        frozen_access_contracts=contracts,
        segment_instructions=plans,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert len(graph.attachments) == 2


def test_advance_right_may_attach_at_a_declared_internal_segment_node() -> None:
    roads = {
        (RoadSource.SWSD, "left-a"): _road(
            "left-a", "n0", "internal", [(0, 0), (5, 0)]
        ),
        (RoadSource.SWSD, "left-b"): _road(
            "left-b", "internal", "n1", [(5, 0), (10, 0)]
        ),
        (RoadSource.SWSD, "right"): _road(
            "right", "n2", "n3", [(15, 0), (20, 0)]
        ),
        (RoadSource.SWSD, "ar"): _road(
            "ar", "internal", "n2", [(5, 0), (15, 0)]
        ),
    }
    nodes = {
        (RoadSource.SWSD, node_id): _node(node_id, x)
        for node_id, x in (
            ("n0", 0),
            ("internal", 5),
            ("n1", 10),
            ("n2", 15),
            ("n3", 20),
        )
    }
    skeleton = {
        "segments": [
            _standard("left", ("n0", "n1"), ("left-a", "left-b")),
            _standard("right", ("n2", "n3"), ("right",)),
            _advance_right(
                "ar",
                ("ar",),
                "left@internal",
                "right@n2",
            ),
        ]
    }
    plans, contracts, blockers = (
        build_t01_fallback_materialization_instructions(
            skeleton,
            source_roads=roads,
            source_nodes=nodes,
        )
    )
    assert blockers == ()
    left = next(row for row in plans if row.segment_id == "left")
    binding = next(
        row
        for row in left.access_bindings
        if row.access_node_id == "internal"
    )
    assert (
        binding.structural_role.value
        == "ADVANCE_RIGHT_ATTACHMENT"
    )
    assert binding.road_instruction_ids == (
        "swsd:left:left-a",
        "swsd:left:left-b",
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right", "ar"),
        frozen_access_contracts=contracts,
        segment_instructions=plans,
        source_roads=roads,
        source_nodes=nodes,
    )
    assert len(graph.attachments) == 2
