from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import RoadRecord
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association_gates import (
    _build_support_fragment,
)


def _road() -> RoadRecord:
    return RoadRecord(
        feature_index=0,
        road_id="road",
        snodeid="1",
        enodeid="2",
        direction=2,
        geometry=LineString([(0, 5), (50, 5)]),
    )


def test_support_fragment_requires_local_overlap_of_allowed_space_and_selected_corridor() -> None:
    fragment = _build_support_fragment(
        _road(),
        allowed_space=box(0, 0, 10, 10),
        selected_corridor=box(35, 0, 45, 10),
        anchor_point=Point(5, 5),
    )

    assert fragment is None


def test_support_fragment_keeps_road_when_local_allowed_fragment_overlaps_corridor() -> None:
    fragment = _build_support_fragment(
        _road(),
        allowed_space=box(0, 0, 10, 10),
        selected_corridor=box(5, 0, 15, 10),
        anchor_point=Point(5, 5),
    )

    assert fragment is not None
    assert fragment.length > 0
