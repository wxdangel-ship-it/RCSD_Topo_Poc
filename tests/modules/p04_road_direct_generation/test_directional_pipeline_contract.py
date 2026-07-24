from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    DirectionalRoadV2Config,
    run_directional_road_v2,
)


def test_directional_v2_keeps_milestone_two_in_an_isolated_subdirectory(
    tmp_path: Path,
) -> None:
    config = DirectionalRoadV2Config(
        patch_root=tmp_path / "patches",
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "v2",
        run_id="directional-v2",
        expected_parent_road_count=571,
    )

    milestone_two = config.milestone_two_config()

    assert milestone_two.output_dir == tmp_path / "v2" / "_milestone2"
    assert milestone_two.run_id == "directional-v2_m2"
    assert milestone_two.expected_road_count == 571
    assert callable(run_directional_road_v2)
