from __future__ import annotations

from pathlib import Path

from .schemas import T06PrecheckArtifacts
from .step1_identify_fusion_units import run_t06_step1_identify_fusion_units
from .step2_extract_rcsd_segments import run_t06_step2_extract_rcsd_segments


def run_t06_segment_fusion_precheck(
    *,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    intersection_match_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    max_main_axis_angle_diff_deg: float = 60.0,
    min_coarse_length_ratio: float = 0.4,
    max_coarse_length_ratio: float = 2.5,
    buffer_distance_m: float = 50.0,
    min_buffer_road_overlap_ratio: float = 0.2,
    min_buffer_road_overlap_length_m: float = 1.0,
    advance_right_formway_bit: int = 128,
    progress: bool = False,
    write_json_outputs: bool = True,
) -> T06PrecheckArtifacts:
    step1 = run_t06_step1_identify_fusion_units(
        swsd_segment_path=swsd_segment_path,
        swsd_nodes_path=swsd_nodes_path,
        out_root=out_root,
        run_id=run_id,
        progress=progress,
    )
    step2 = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=step1.final_fusion_units_gpkg_path or step1.fusion_units_gpkg_path,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        swsd_nodes_path=swsd_nodes_path,
        intersection_match_path=intersection_match_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id=step1.run_id,
        max_main_axis_angle_diff_deg=max_main_axis_angle_diff_deg,
        min_coarse_length_ratio=min_coarse_length_ratio,
        max_coarse_length_ratio=max_coarse_length_ratio,
        buffer_distance_m=buffer_distance_m,
        min_buffer_road_overlap_ratio=min_buffer_road_overlap_ratio,
        min_buffer_road_overlap_length_m=min_buffer_road_overlap_length_m,
        advance_right_formway_bit=advance_right_formway_bit,
        progress=progress,
        write_json_outputs=write_json_outputs,
    )
    return T06PrecheckArtifacts(run_id=step1.run_id, run_root=step1.run_root, step1=step1, step2=step2)
