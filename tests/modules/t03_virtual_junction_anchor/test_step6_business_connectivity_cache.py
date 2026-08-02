from unittest.mock import patch

from shapely.geometry import Point, box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import (
    step6_business_connectivity as connectivity,
)


def test_connectivity_cache_reuses_membership_without_changing_audit() -> None:
    source = box(0.0, 0.0, 20.0, 10.0)
    output = box(0.0, 0.0, 20.0, 10.0)
    terminals = {
        "left": Point(1.0, 5.0),
        "right": Point(19.0, 5.0),
    }
    expected = connectivity.build_business_connectivity_audit(
        source_surface=source,
        output_surface=output,
        terminals=terminals,
    )
    cache = connectivity.BusinessConnectivityCache()

    with patch.object(
        connectivity,
        "_terminal_component_ids",
        wraps=connectivity._terminal_component_ids,
    ) as membership_spy:
        first = connectivity.build_business_connectivity_audit(
            source_surface=source,
            output_surface=output,
            terminals=terminals,
            cache=cache,
        )
        calls_after_first = membership_spy.call_count
        second = connectivity.build_business_connectivity_audit(
            source_surface=source,
            output_surface=output,
            terminals=terminals,
            cache=cache,
        )

    assert first == expected
    assert second == expected
    assert calls_after_first == 4
    assert membership_spy.call_count == calls_after_first


def test_connectivity_cache_distinguishes_replaced_terminal_geometry() -> None:
    surface = box(0.0, 0.0, 20.0, 10.0)
    cache = connectivity.BusinessConnectivityCache()
    first = connectivity.build_business_connectivity_audit(
        source_surface=surface,
        output_surface=surface,
        terminals={"terminal": Point(1.0, 5.0)},
        cache=cache,
    )
    second = connectivity.build_business_connectivity_audit(
        source_surface=surface,
        output_surface=surface,
        terminals={"terminal": Point(30.0, 5.0)},
        cache=cache,
    )

    assert first["output_missing_terminal_ids"] == []
    assert second["output_missing_terminal_ids"] == ["terminal"]
