from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .road_config import MilestoneTwoConfig


@dataclass(frozen=True)
class DirectionalRoadV2Config:
    patch_root: Path
    swsd_road_path: Path
    swsd_node_path: Path
    output_dir: Path
    run_id: str
    t01_road_path: Path | None = None
    t01_segment_path: Path | None = None
    current_rcsd_road_path: Path | None = None
    analysis_crs: str = "EPSG:32650"
    hard_evidence_quality_state: str = "usable"
    support_full_coverage_ratio: float = 0.95
    support_max_gap_m: float = 10.0
    long_sd_gap_review_m: float = 100.0
    cross_direction_min_absolute_separation_m: float = 0.5
    cross_direction_min_lane_width_ratio: float = 0.5
    cross_direction_sample_spacing_m: float = 1.0
    fit_station_spacing_m: float = 5.0
    anchor_max_distance_m: float = 30.0
    smoothing_passes: int = 12
    max_adjacent_lateral_shift_m: float = 2.0
    max_lateral_slope: float = 0.09
    max_total_variation_per_100m: float = 12.0
    max_candidate_length_ratio: float = 1.08
    lane_group_envelope_tolerance_m: float = 0.75
    non_simple_simplify_tolerance_m: float = 1.0
    endpoint_transition_length_m: float = 20.0
    physical_node_snap_tolerance_m: float = 0.05
    movement_evidence_geometry_max_distance_m: float = 20.0
    movement_max_join_angle_deg: float = 10.0
    movement_curve_sample_spacing_m: float = 0.25
    expected_parent_road_count: int | None = None

    def resolved(self) -> "DirectionalRoadV2Config":
        return DirectionalRoadV2Config(
            **{
                **asdict(self),
                "patch_root": self.patch_root.expanduser().resolve(),
                "swsd_road_path": self.swsd_road_path.expanduser().resolve(),
                "swsd_node_path": self.swsd_node_path.expanduser().resolve(),
                "output_dir": self.output_dir.expanduser().resolve(),
                "t01_road_path": _resolve_optional(self.t01_road_path),
                "t01_segment_path": _resolve_optional(self.t01_segment_path),
                "current_rcsd_road_path": _resolve_optional(self.current_rcsd_road_path),
            }
        )

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
class DirectionalRoadV2Result:
    run_id: str
    output_dir: Path
    summary_path: Path
    report_path: Path
    core_gate_pass: bool


def _resolve_optional(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None


__all__ = ["DirectionalRoadV2Config", "DirectionalRoadV2Result"]
