from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry


PROCESS_CRS_TEXT = "EPSG:3857"
RELATION_OUTPUT_CRS_NAME = "CRS84"

STATUS_SUCCESS = 0
STATUS_FAILURE = 1

SCENE_DIRECT = "direct_existing_rcsd_junction"
SCENE_GROUP_EXISTING = "group_existing_rcsd_nodes"
SCENE_ROAD_SPLIT = "road_only_split"
SCENE_NO_RCSD = "no_related_rcsd"
SCENE_FAILURE = "failure"

RELATION_FIELDS = ["target_id", "base_id", "status", "level", "is_highway"]

BLOCKING_ERROR_FIELDS = [
    "target_id",
    "surface_id",
    "reason",
    "base_id_candidates",
    "source_modules",
    "source_case_ids",
    "notes",
]

JUNCTIONIZATION_AUDIT_FIELDS = [
    "target_id",
    "surface_id",
    "source_module",
    "source_case_id",
    "scene",
    "action",
    "status",
    "base_id",
    "reason",
    "original_rcsdroad_ids",
    "new_rcsdroad_ids",
    "original_rcsdnode_ids",
    "new_rcsdnode_ids",
    "grouped_rcsdnode_ids",
    "selected_main_rcsdnode_id",
    "projection_point_count",
    "split_point_count",
    "skipped_reason",
    "geometry_mode",
    "multi_base_relation",
    "blocking_error",
]


@dataclass(frozen=True)
class Phase2Evidence:
    source_module: str
    row: dict[str, Any]
    target_id: str
    case_id: str | None


@dataclass(frozen=True)
class SceneDecision:
    scene: str
    action: str
    reason: str
    source_module: str
    source_case_id: str | None
    base_id_candidates: tuple[int, ...] = ()
    rcsdnode_ids: tuple[int, ...] = ()
    rcsdroad_ids: tuple[int, ...] = ()
    reference_mode: str = "swsd"
    multi_base_relation: bool = False


@dataclass(frozen=True)
class SwsdTargetContext:
    target_id: str
    surface_id: str
    junction_type: str
    point: BaseGeometry
    projection_points: tuple[BaseGeometry, ...]
    level: Any = -1
    is_highway: Any = -1
    representative_properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SplitPoint:
    road_id: int
    distance_m: float
    geometry: BaseGeometry


@dataclass(frozen=True)
class RoadSplitResult:
    new_road_features: list[dict[str, Any]]
    new_node_features: list[dict[str, Any]]
    original_road_ids: list[int]
    skipped_reasons: list[str]


@dataclass(frozen=True)
class T05Phase2Artifacts:
    run_root: Path
    relation_geojson_path: Path
    rcsdroad_out_path: Path
    rcsdnode_out_path: Path
    rcsdroad_split_path: Path
    rcsdnode_generated_path: Path
    rcsdnode_grouped_path: Path
    rcsd_junctionization_audit_csv_path: Path
    rcsd_junctionization_audit_json_path: Path
    relation_audit_csv_path: Path
    relation_audit_json_path: Path
    blocking_errors_csv_path: Path
    blocking_errors_json_path: Path
    summary_path: Path
    relation_count: int
    success_count: int
    failure_count: int
