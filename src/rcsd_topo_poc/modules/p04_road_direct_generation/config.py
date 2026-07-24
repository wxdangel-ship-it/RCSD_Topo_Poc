from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MilestoneOneConfig:
    patch_root: Path
    swsd_road_path: Path
    swsd_node_path: Path
    output_dir: Path
    run_id: str
    t01_road_path: Path | None = None
    t01_segment_path: Path | None = None
    current_rcsd_road_path: Path | None = None
    analysis_crs: str = "EPSG:32650"
    lane_sample_spacing_m: float = 8.0
    lane_min_samples: int = 3
    lane_max_samples: int = 9
    owner_search_radius_m: float = 80.0
    owner_max_p90_distance_m: float = 20.0
    owner_review_max_p90_distance_m: float = 30.0
    owner_max_direction_delta_deg: float = 35.0
    owner_review_max_direction_delta_deg: float = 50.0
    owner_min_score_margin: float = 5.0
    owner_candidate_limit: int = 3
    boundary_search_radius_m: float = 12.0
    boundary_max_direction_delta_deg: float = 35.0
    boundary_owner_corridor_radius_m: float = 35.0
    width_min_bilateral_coverage: float = 0.75
    width_min_review_coverage: float = 0.50
    width_narrow_candidate_m: float = 2.50
    width_wide_candidate_m: float = 5.00
    width_max_p90_p10_variation_m: float = 2.50
    drivezone_min_coverage: float = 0.80

    def resolved(self) -> "MilestoneOneConfig":
        return MilestoneOneConfig(
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

    def parameter_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class MilestoneOneResult:
    run_id: str
    output_dir: Path
    summary_path: Path
    report_path: Path
    core_gate_pass: bool


def _resolve_optional(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None
