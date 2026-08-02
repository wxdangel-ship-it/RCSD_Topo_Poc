from shapely.geometry import Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_business_connectivity import (
    build_business_connectivity_audit,
)


def test_connected_source_split_output_is_mismatch() -> None:
    audit = build_business_connectivity_audit(
        source_surface=box(0, 0, 30, 10),
        output_surface=unary_union([box(0, 0, 10, 10), box(20, 0, 30, 10)]),
        terminals={"left": Point(5, 5), "right": Point(25, 5)},
    )

    assert audit["comparable"] is True
    assert audit["equivalent"] is False
    assert audit["mismatches"][0]["mismatch_type"] == "source_connected_output_split"


def test_split_source_and_split_output_are_equivalent() -> None:
    surface = unary_union([box(0, 0, 10, 10), box(20, 0, 30, 10)])
    audit = build_business_connectivity_audit(
        source_surface=surface,
        output_surface=surface,
        terminals={"left": Point(5, 5), "right": Point(25, 5)},
    )

    assert audit["comparable"] is True
    assert audit["equivalent"] is True
    assert audit["mismatches"] == []


def test_split_source_connected_output_is_mismatch() -> None:
    audit = build_business_connectivity_audit(
        source_surface=unary_union([box(0, 0, 10, 10), box(20, 0, 30, 10)]),
        output_surface=box(0, 0, 30, 10),
        terminals={"left": Point(5, 5), "right": Point(25, 5)},
    )

    assert audit["equivalent"] is False
    assert audit["mismatches"][0]["mismatch_type"] == "source_split_output_connected"


def test_missing_source_terminal_is_not_comparable() -> None:
    audit = build_business_connectivity_audit(
        source_surface=box(0, 0, 10, 10),
        output_surface=box(0, 0, 10, 10),
        terminals={"inside": Point(5, 5), "outside": Point(25, 5)},
    )

    assert audit["comparable"] is False
    assert audit["equivalent"] is False
    assert audit["source_missing_terminal_ids"] == ["outside"]
