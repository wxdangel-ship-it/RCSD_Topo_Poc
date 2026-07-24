from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .road_config import MilestoneTwoConfig


@dataclass(frozen=True)
class HighPrecisionRoadV3Config:
    patch_root: Path
    swsd_road_path: Path
    swsd_node_path: Path
    output_dir: Path
    run_id: str
    t01_road_path: Path | None = None
    t01_segment_path: Path | None = None
    current_rcsd_road_path: Path | None = None
    frozen_v2_root: Path | None = None
    analysis_crs: str = "EPSG:32650"
    hard_evidence_quality_state: str = "usable"
    physical_split_min_shared_coverage_ratio: float = 0.5
    cross_direction_min_absolute_separation_m: float = 0.5
    cross_direction_min_lane_width_ratio: float = 0.5
    cross_direction_sample_spacing_m: float = 2.0
    fit_station_spacing_m: float = 5.0
    observation_longitudinal_tolerance_m: float = 7.5
    anchor_max_distance_m: float = 30.0
    drivezone_tolerance_m: float = 1.5
    smoothing_passes: int = 12
    max_adjacent_lateral_shift_m: float = 2.0
    max_lateral_slope: float = 0.09
    max_hp_lateral_oscillation_per_100m: float = 12.0
    max_candidate_length_ratio: float = 1.08
    lane_group_envelope_tolerance_m: float = 0.75
    physical_node_snap_tolerance_m: float = 0.05
    physical_node_coordination_trigger_m: float = 1e-8
    endpoint_transition_length_m: float = 20.0
    endpoint_geometry_sample_spacing_m: float = 1.0
    endpoint_both_transition_cap_ratio: float = 0.33
    endpoint_single_transition_cap_ratio: float = 0.55
    movement_evidence_geometry_max_distance_m: float = 20.0
    movement_max_join_angle_deg: float = 10.0
    movement_curve_sample_spacing_m: float = 0.1
    minimum_evidence_road_control_ratio: float = 0.8
    maximum_network_swsd_fallback_ratio: float = 0.4
    expected_parent_road_count: int | None = None

    def resolved(self) -> "HighPrecisionRoadV3Config":
        payload = asdict(self)
        for key in (
            "patch_root",
            "swsd_road_path",
            "swsd_node_path",
            "output_dir",
            "t01_road_path",
            "t01_segment_path",
            "current_rcsd_road_path",
            "frozen_v2_root",
        ):
            value = payload[key]
            payload[key] = value.expanduser().resolve() if value is not None else None
        return HighPrecisionRoadV3Config(**payload)

    def milestone_two_config(self) -> MilestoneTwoConfig:
        return MilestoneTwoConfig(
            patch_root=self.patch_root,
            swsd_road_path=self.swsd_road_path,
            swsd_node_path=self.swsd_node_path,
            output_dir=self.output_dir / "_milestone2",
            run_id=f"{self.run_id}_m2",
            t01_road_path=self.t01_road_path,
            t01_segment_path=self.t01_segment_path,
            current_rcsd_road_path=self.current_rcsd_road_path,
            analysis_crs=self.analysis_crs,
            expected_road_count=self.expected_parent_road_count,
        )

    def parameter_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class HighPrecisionRoadV3Result:
    run_id: str
    output_dir: Path
    summary_path: Path
    report_path: Path
    core_gate_pass: bool


__all__ = ["HighPrecisionRoadV3Config", "HighPrecisionRoadV3Result"]
