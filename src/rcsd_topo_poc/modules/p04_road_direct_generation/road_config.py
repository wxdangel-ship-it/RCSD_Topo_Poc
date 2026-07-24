from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import MilestoneOneConfig


@dataclass(frozen=True)
class MilestoneTwoConfig:
    patch_root: Path
    swsd_road_path: Path
    swsd_node_path: Path
    output_dir: Path
    run_id: str
    t01_road_path: Path | None = None
    t01_segment_path: Path | None = None
    current_rcsd_road_path: Path | None = None
    analysis_crs: str = "EPSG:32650"
    lane_segment_sample_spacing_m: float = 5.0
    lane_segment_search_radius_m: float = 35.0
    lane_segment_max_distance_m: float = 20.0
    lane_segment_max_direction_delta_deg: float = 35.0
    lane_segment_candidate_limit: int = 5
    lane_segment_adjacent_transition_penalty: float = 3.0
    lane_segment_unrelated_transition_penalty: float = 30.0
    support_full_coverage_ratio: float = 0.95
    support_max_gap_m: float = 10.0
    fit_station_spacing_m: float = 5.0
    fit_transition_length_m: float = 10.0
    fit_max_lane_distance_m: float = 25.0
    expected_road_count: int | None = None

    def resolved(self) -> "MilestoneTwoConfig":
        return MilestoneTwoConfig(
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

    def milestone_one_config(self) -> MilestoneOneConfig:
        return MilestoneOneConfig(
            patch_root=self.patch_root,
            swsd_road_path=self.swsd_road_path,
            swsd_node_path=self.swsd_node_path,
            output_dir=self.output_dir / "_milestone1",
            run_id=f"{self.run_id}_m1",
            t01_road_path=self.t01_road_path,
            t01_segment_path=self.t01_segment_path,
            current_rcsd_road_path=self.current_rcsd_road_path,
            analysis_crs=self.analysis_crs,
        )

    def parameter_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class MilestoneTwoResult:
    run_id: str
    output_dir: Path
    summary_path: Path
    report_path: Path
    core_gate_pass: bool


def _resolve_optional(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None


__all__ = ["MilestoneTwoConfig", "MilestoneTwoResult"]
