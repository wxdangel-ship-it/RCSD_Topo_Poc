from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Step3SurfaceRuntimeState:
    step_root: Path
    swsd_segments: list[dict[str, Any]]
    swsd_roads: list[dict[str, Any]]
    swsd_nodes: list[dict[str, Any]]
    step2_replaceable_rows: list[dict[str, Any]]
    frcsd_roads: list[dict[str, Any]]
    frcsd_nodes: list[dict[str, Any]]
    segment_relation_rows: list[dict[str, Any]]
    semantic_junction_group_rows: list[dict[str, Any]]
    advance_right_audit_rows: list[dict[str, Any]]
    connectivity_supplement_road_ids: set[str]
    deferred_publish_jobs: dict[str, Any] = field(default_factory=dict)
    deferred_publish_fieldnames: dict[str, list[str]] = field(default_factory=dict)
    surface_topology_audit_rows: list[dict[str, Any]] = field(default_factory=list)
    topology_connectivity_audit_rows: list[dict[str, Any]] = field(default_factory=list)
    authoritative_transition_closure_rows: list[dict[str, Any]] = field(default_factory=list)
    publish_topology_connectivity_json: bool = False


_LATEST_STATE: ContextVar[Step3SurfaceRuntimeState | None] = ContextVar(
    "t06_step3_surface_runtime_state",
    default=None,
)


def publish_step3_surface_runtime_state(state: Step3SurfaceRuntimeState) -> None:
    normalize_step3_surface_runtime_state(state)
    _LATEST_STATE.set(state)


def normalize_step3_surface_runtime_state(state: Step3SurfaceRuntimeState) -> None:
    for rows in (
        state.frcsd_roads,
        state.frcsd_nodes,
        state.segment_relation_rows,
    ):
        normalize_vector_roundtrip_properties(rows)
    for row in state.topology_connectivity_audit_rows:
        properties = row.get("properties") or {}
        value = properties.get("topology_road_lineage_id")
        if not value or value in ("[]", "{}"):
            properties["topology_road_lineage_id"] = ""


def take_step3_surface_runtime_state(step_root: Path) -> Step3SurfaceRuntimeState | None:
    state = _LATEST_STATE.get()
    _LATEST_STATE.set(None)
    if state is None or state.step_root.resolve() != step_root.resolve():
        return None
    return state


def normalize_vector_roundtrip_properties(rows: list[dict[str, Any]]) -> None:
    """Match the property representation returned after a GPKG round trip."""

    for row in rows:
        properties = row.get("properties") or {}
        for key, value in list(properties.items()):
            if value is None or isinstance(value, (bool, int, float, str)):
                continue
            if isinstance(value, Path):
                properties[key] = str(value)
                continue
            properties[key] = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
