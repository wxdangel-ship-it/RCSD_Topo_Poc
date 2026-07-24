from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_types import (
    CarrierRealization,
    JunctionSource,
    ReplacementScope,
    SegmentState,
    validate_publication_state,
)


def test_segment_first_state_values_are_business_contract() -> None:
    assert {item.value for item in SegmentState} == {
        "hp_full",
        "hp_partial",
        "swsd_retained",
        "conflict_retained",
    }
    assert {item.value for item in CarrierRealization} == {"built", "retained"}
    assert {item.value for item in ReplacementScope} == {"all", "subset", "none"}
    assert JunctionSource.T07_ACCEPTED.value == "t07_accepted"


@pytest.mark.parametrize(
    ("state", "scope", "built", "retained"),
    [
        (SegmentState.HP_FULL, ReplacementScope.ALL, 2, 0),
        (SegmentState.HP_PARTIAL, ReplacementScope.SUBSET, 1, 1),
        (SegmentState.SWSD_RETAINED, ReplacementScope.NONE, 0, 1),
        (SegmentState.CONFLICT_RETAINED, ReplacementScope.NONE, 0, 2),
    ],
)
def test_valid_publication_state_combinations(
    state: SegmentState,
    scope: ReplacementScope,
    built: int,
    retained: int,
) -> None:
    validate_publication_state(state, scope, built, retained)


def test_hp_full_cannot_retain_swsd_carrier() -> None:
    with pytest.raises(ValueError, match="hp_full"):
        validate_publication_state(
            SegmentState.HP_FULL,
            ReplacementScope.ALL,
            built_count=1,
            retained_count=1,
        )


def test_config_rejects_output_inside_input(tmp_path: Path) -> None:
    input_root = tmp_path / "case"
    input_root.mkdir()
    kwargs = _required_paths(input_root)
    config = SegmentFirstConfig(
        **kwargs,
        output_dir=input_root / "out",
        run_id="segment-first-test",
    )
    with pytest.raises(ValueError, match="output_dir"):
        config.validate_paths(require_files=False)


def _required_paths(root: Path) -> dict[str, Path]:
    return {
        "patch_root": root / "patch",
        "swsd_road_path": root / "swsd_road.gpkg",
        "swsd_node_path": root / "swsd_node.gpkg",
        "t01_road_path": root / "t01_road.gpkg",
        "t01_node_path": root / "t01_node.gpkg",
        "t01_segment_path": root / "t01_segment.gpkg",
        "t07_surface_path": root / "t07.gpkg",
        "t03_surface_path": root / "t03.gpkg",
        "t04_surface_path": root / "t04.gpkg",
        "full_rcsd_road_path": root / "rcsd_road.gpkg",
        "full_rcsd_node_path": root / "rcsd_node.gpkg",
    }
