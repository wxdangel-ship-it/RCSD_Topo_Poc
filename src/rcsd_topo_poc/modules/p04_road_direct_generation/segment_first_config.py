from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from pyproj import CRS


@dataclass(frozen=True)
class SegmentFirstConfig:
    patch_root: Path
    swsd_road_path: Path
    swsd_node_path: Path
    t01_road_path: Path
    t01_node_path: Path
    t01_segment_path: Path
    t07_surface_path: Path
    t03_surface_path: Path
    t04_surface_path: Path
    full_rcsd_road_path: Path
    full_rcsd_node_path: Path
    output_dir: Path
    run_id: str
    analysis_crs: str = "EPSG:32650"
    target_replaceability_path: Path | None = None
    target_disposition_path: Path | None = None
    frozen_v2_root: Path | None = None
    frozen_v3_root: Path | None = None
    assignment_max_distance_m: float = 35.0
    assignment_max_angle_deg: float = 70.0
    lane_recovery_max_distance_m: float = 25.0
    lane_recovery_max_angle_deg: float = 35.0
    full_rcsd_anchor_max_distance_m: float = 8.0
    full_rcsd_anchor_max_angle_deg: float = 35.0
    member_takeover_min_coverage: float = 0.60
    endpoint_snap_distance_m: float = 3.0
    relation_endpoint_max_distance_m: float = 20.0
    junction_endpoint_buffer_m: float = 1.0
    completion_surface_buffer_m: float = 1.0
    completion_surface_min_coverage: float = 0.90
    completion_hard_max_turn_deg: float = 75.0
    completion_source_turn_exemption_deg: float = 45.0
    completion_review_turn_deg: float = 45.0
    completion_review_length_ratio: float = 2.0
    completion_review_hausdorff_m: float = 20.0
    smoothing_sample_spacing_m: float = 2.0
    smoothing_max_deviation_m: float = 1.5
    lineage_split_min_part_length_m: float = 10.0
    lineage_split_max_handoff_gap_m: float = 15.0
    lineage_split_max_handoff_overlap_m: float = 10.0
    lineage_lane_group_max_distance_m: float = 20.0
    output_source_built: int = 1
    output_source_retained: int = 2

    def resolved(self) -> "SegmentFirstConfig":
        path_fields = {
            name: value.expanduser().resolve()
            for name, value in self.__dict__.items()
            if isinstance(value, Path)
        }
        return replace(self, **path_fields)

    def validate_paths(self, *, require_files: bool = True) -> None:
        cfg = self.resolved()
        if not cfg.run_id.strip():
            raise ValueError("run_id must be non-empty")
        crs = CRS.from_user_input(cfg.analysis_crs)
        if not crs.is_projected:
            raise ValueError("analysis_crs must be a projected CRS")
        inputs = self.input_paths()
        for role, path in inputs.items():
            if require_files and not path.exists():
                raise FileNotFoundError(f"missing {role}: {path}")
            if _is_relative_to(cfg.output_dir, path):
                raise ValueError(f"input path is inside output_dir: {role}={path}")
            if _is_relative_to(cfg.output_dir, path.parent) or _is_relative_to(path, cfg.output_dir):
                raise ValueError("output_dir must not overlap any input path")
        if cfg.output_dir.exists() and any(cfg.output_dir.iterdir()):
            raise FileExistsError(f"output_dir must be new or empty: {cfg.output_dir}")

    def input_paths(self) -> dict[str, Path]:
        cfg = self.resolved()
        inputs = {
            "patch_root": cfg.patch_root,
            "swsd_roads": cfg.swsd_road_path,
            "swsd_nodes": cfg.swsd_node_path,
            "t01_roads": cfg.t01_road_path,
            "t01_nodes": cfg.t01_node_path,
            "t01_segments": cfg.t01_segment_path,
            "t07_surface": cfg.t07_surface_path,
            "t03_surface": cfg.t03_surface_path,
            "t04_surface": cfg.t04_surface_path,
            "full_rcsd_roads": cfg.full_rcsd_road_path,
            "full_rcsd_nodes": cfg.full_rcsd_node_path,
        }
        if cfg.target_replaceability_path is not None:
            inputs["target_replaceability"] = cfg.target_replaceability_path
        if cfg.target_disposition_path is not None:
            inputs["target_disposition"] = cfg.target_disposition_path
        return inputs

    def parameters(self) -> dict[str, object]:
        excluded = {
            "patch_root",
            "swsd_road_path",
            "swsd_node_path",
            "t01_road_path",
            "t01_node_path",
            "t01_segment_path",
            "t07_surface_path",
            "t03_surface_path",
            "t04_surface_path",
            "full_rcsd_road_path",
            "full_rcsd_node_path",
            "target_replaceability_path",
            "target_disposition_path",
            "output_dir",
            "frozen_v2_root",
            "frozen_v3_root",
        }
        return {key: value for key, value in self.__dict__.items() if key not in excluded}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


__all__ = ["SegmentFirstConfig"]
