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
    authoritative_transition_closure_rows: list[dict[str, Any]] = field(default_factory=list)


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
        state.semantic_junction_group_rows,
        state.advance_right_audit_rows,
    ):
        _normalize_vector_roundtrip_properties(rows)


def take_step3_surface_runtime_state(step_root: Path) -> Step3SurfaceRuntimeState | None:
    state = _LATEST_STATE.get()
    _LATEST_STATE.set(None)
    if state is None or state.step_root.resolve() != step_root.resolve():
        return None
    return state


def _normalize_vector_roundtrip_properties(rows: list[dict[str, Any]]) -> None:
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
