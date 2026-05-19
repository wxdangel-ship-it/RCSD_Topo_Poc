from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry


TARGET_CRS_TEXT = "EPSG:3857"

SOURCE_T02_INPUT = "T02_INPUT"
SOURCE_T03 = "T03"
SOURCE_T04 = "T04"
SOURCE_ORDER = (SOURCE_T02_INPUT, SOURCE_T03, SOURCE_T04)

ALLOWED_SURFACE_SOURCES = {
    SOURCE_T02_INPUT,
    SOURCE_T03,
    SOURCE_T04,
    f"{SOURCE_T02_INPUT}|{SOURCE_T03}",
    f"{SOURCE_T02_INPUT}|{SOURCE_T04}",
    f"{SOURCE_T03}|{SOURCE_T04}",
    f"{SOURCE_T02_INPUT}|{SOURCE_T03}|{SOURCE_T04}",
}

MAIN_SURFACE_FIELDS = [
    "surface_id",
    "mainnodeid",
    "patch_id",
    "junction_type",
    "kind_2",
    "surface_sources",
    "is_multi_source_merged",
]

AUDIT_FIELDS = [
    "surface_id",
    "fusion_group_id",
    "mainnodeid",
    "patch_id",
    "kind_2",
    "junction_type",
    "surface_sources",
    "is_multi_source_merged",
    "source_count",
    "source_feature_ids",
    "source_case_ids",
    "source_modules",
    "source_patch_ids",
    "geometry_action",
    "fusion_action",
    "conflict_state",
    "conflict_reason",
    "selected_primary_source",
    "dropped_source_ids",
    "geometry_cleaned",
    "notes",
]

SKIPPED_FIELDS = [
    "source",
    "source_feature_id",
    "source_case_id",
    "skip_reason",
    "notes",
]

JUNCTION_TYPE_BY_SOURCE_KIND = {
    (SOURCE_T03, 4): "center_junction",
    (SOURCE_T03, 2048): "single_sided_t_mouth",
    (SOURCE_T04, 8): "merge",
    (SOURCE_T04, 16): "diverge",
    (SOURCE_T04, 128): "complex_divmerge",
}

T03_KIND_VALUES = {4, 2048}
T04_KIND_VALUES = {8, 16, 128}


@dataclass(frozen=True)
class SourceSurface:
    source: str
    source_feature_id: str
    source_case_id: str | None
    geometry: BaseGeometry
    mainnodeid: str | None
    patch_id: str | None
    kind_2: int | None
    junction_type: str
    properties: dict[str, Any]
    source_index: int
    geometry_cleaned: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FusionResult:
    surface_feature: dict[str, Any] | None
    audit_row: dict[str, Any]
    conflict_feature: dict[str, Any] | None = None


@dataclass(frozen=True)
class T05Phase1Artifacts:
    run_root: Path
    surface_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    summary_path: Path
    skipped_csv_path: Path | None
    skipped_json_path: Path | None
    published_surface_count: int
    conflict_count: int
    skipped_count: int
