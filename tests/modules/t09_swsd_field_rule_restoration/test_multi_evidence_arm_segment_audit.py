import csv
import json
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    RestorationStrategy,
    RestorationResult,
    SWSDSegmentInput,
    SWSDRoadInput,
    build_swsd_arms,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.outputs import (
    write_restoration_outputs,
)


@pytest.mark.parametrize(
    ("road_segment_ids", "t01_segment_ids", "expected_status"),
    [
        (("seg_a",), ("seg_a",), "consistent"),
        (tuple(), ("seg_a",), "t01_only"),
        (("seg_a",), tuple(), "road_only"),
        (("stale_seg",), ("seg_a",), "conflict"),
        (tuple(), tuple(), "missing"),
    ],
)
def test_arm_segment_membership_audit_has_five_explicit_states(
    road_segment_ids: tuple[str, ...],
    t01_segment_ids: tuple[str, ...],
    expected_status: str,
) -> None:
    road = SWSDRoadInput(
        road_id="road_1",
        snodeid="outside",
        enodeid="junction",
        direction=2,
        segment_ids=road_segment_ids,
    )
    segments = tuple(
        SWSDSegmentInput(segment_id=segment_id, road_ids=(road.road_id,))
        for segment_id in t01_segment_ids
    )

    arm = build_swsd_arms(
        junction_id="junction",
        member_node_ids=("junction",),
        roads=(road,),
        segments=segments,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )[0]

    assert arm.t01_segment_ids == t01_segment_ids
    assert arm.segment_membership_status == expected_status
    assert ("segment_membership_conflict" in arm.risk_flags) is (expected_status == "conflict")


def test_stale_road_segment_cannot_masquerade_as_formal_t01_single_segment(
    tmp_path: Path,
) -> None:
    road_geometries = {
        "road_in": LineString([(10.0, 0.0), (0.0, 0.0)]),
        "road_out": LineString([(0.0, 0.0), (10.0, 0.1)]),
    }
    roads = (
        SWSDRoadInput(
            road_id="road_in",
            snodeid="outside_in",
            enodeid="junction",
            direction=2,
            segment_ids=("stale_shared",),
        ),
        SWSDRoadInput(
            road_id="road_out",
            snodeid="junction",
            enodeid="outside_out",
            direction=2,
            segment_ids=("stale_shared",),
        ),
    )
    segments = (
        SWSDSegmentInput(
            segment_id="official_a",
            junc_nodes=("junction",),
            road_ids=("road_in",),
        ),
        SWSDSegmentInput(
            segment_id="official_b",
            junc_nodes=("junction",),
            road_ids=("road_out",),
        ),
    )

    arms = build_swsd_arms(
        junction_id="junction",
        member_node_ids=("junction",),
        roads=roads,
        segments=segments,
        road_geometries=road_geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert len(arms) == 1
    arm = arms[0]
    # Legacy fields and carrier projection remain unchanged for v1 compatibility.
    assert arm.segment_ids == ("stale_shared",)
    assert arm.connector_road_ids == tuple()
    assert arm.approach_road_ids == ("road_in",)
    assert arm.exit_road_ids == ("road_out",)
    assert arm.trunk_road_ids == ("road_in", "road_out")
    # Formal T01 membership is independently visible and exposes the stale conflict.
    assert arm.t01_segment_ids == ("official_a", "official_b")
    assert arm.segment_membership_status == "conflict"
    assert "segment_membership_conflict" in arm.risk_flags

    artifacts = write_restoration_outputs(
        result=RestorationResult(
            arms=(arm,),
            movements=tuple(),
            evidence_items=tuple(),
            restored_rules=tuple(),
            summary={},
        ),
        output_dir=tmp_path / "outputs",
        road_geometries=road_geometries,
    )

    json_row = json.loads(artifacts.arms_json.read_text(encoding="utf-8"))[0]
    assert json_row["t01_segment_ids"] == ["official_a", "official_b"]
    assert json_row["segment_membership_status"] == "conflict"
    with artifacts.arms_csv.open("r", encoding="utf-8", newline="") as fp:
        csv_row = next(csv.DictReader(fp))
    assert json.loads(csv_row["t01_segment_ids"]) == ["official_a", "official_b"]
    assert csv_row["segment_membership_status"] == "conflict"
    with fiona.open(artifacts.arms_gpkg) as source:
        gpkg_row = next(iter(source))["properties"]
    assert json.loads(gpkg_row["t01_segment_ids"]) == ["official_a", "official_b"]
    assert gpkg_row["segment_membership_status"] == "conflict"


def test_segment_membership_conflict_risk_is_v2_only_but_audit_fields_are_additive() -> None:
    road = SWSDRoadInput(
        road_id="road_1",
        snodeid="outside",
        enodeid="junction",
        direction=2,
        segment_ids=("stale",),
    )
    kwargs = {
        "junction_id": "junction",
        "member_node_ids": ("junction",),
        "roads": (road,),
        "segments": (
            SWSDSegmentInput(segment_id="official", road_ids=(road.road_id,)),
        ),
    }

    default_v1 = build_swsd_arms(**kwargs)[0]
    explicit_v1 = build_swsd_arms(
        **kwargs,
        strategy_version=RestorationStrategy.RESTRICTION_ONLY_V1,
    )[0]
    explicit_v2 = build_swsd_arms(
        **kwargs,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )[0]

    assert default_v1 == explicit_v1
    assert default_v1.segment_membership_status == "conflict"
    assert default_v1.t01_segment_ids == ("official",)
    assert "segment_membership_conflict" not in default_v1.risk_flags
    assert "segment_membership_conflict" in explicit_v2.risk_flags
