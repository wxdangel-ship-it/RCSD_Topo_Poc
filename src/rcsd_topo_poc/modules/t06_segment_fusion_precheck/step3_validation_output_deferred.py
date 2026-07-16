from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import _feature_json, read_features, suppress_feature_json_outputs, write_json
from .parallel_output import FeatureTripletJob, publish_feature_triplets
from .schemas import (
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_authoritative_transition_closure import (
    AUTHORITATIVE_TRANSITION_CLOSURE_FIELDS,
    AUTHORITATIVE_TRANSITION_CLOSURE_STEM,
)
from .step3_surface_runtime import (
    Step3SurfaceRuntimeState,
    normalize_step3_surface_runtime_state,
)
from .step3_surface_topology_audit import (
    SURFACE_TOPOLOGY_AUDIT_FIELDS,
    SURFACE_TOPOLOGY_AUDIT_STEM,
)
from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
)


_FINAL_PUBLISH_WORKERS = 2


def publish_deferred_validation_outputs(
    state: Step3SurfaceRuntimeState,
    final_step_root: Path,
    *,
    excluded_job_names: set[str] | None = None,
) -> dict[str, dict[str, Path]]:
    """Materialize the final validation state once after every gate has settled."""
    normalize_step3_surface_runtime_state(state)
    jobs = {
        name: FeatureTripletJob(
            job.stem,
            job.features,
            state.deferred_publish_fieldnames.get(name, job.fieldnames),
        )
        for name, job in state.deferred_publish_jobs.items()
    }
    jobs.update(
        {
            "road": FeatureTripletJob(
                STEP3_FRCSD_ROAD_STEM,
                state.frcsd_roads,
                _fieldnames(state, "road"),
            ),
            "node": FeatureTripletJob(
                STEP3_FRCSD_NODE_STEM,
                state.frcsd_nodes,
                _fieldnames(state, "node"),
            ),
            "segment_relation": FeatureTripletJob(
                STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
                state.segment_relation_rows,
                STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
            ),
            "surface_topology": FeatureTripletJob(
                SURFACE_TOPOLOGY_AUDIT_STEM,
                state.surface_topology_audit_rows,
                SURFACE_TOPOLOGY_AUDIT_FIELDS,
            ),
            "topology_connectivity": FeatureTripletJob(
                STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
                state.topology_connectivity_audit_rows,
                STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
            ),
        }
    )
    jobs["authoritative_transition_closure"] = FeatureTripletJob(
        AUTHORITATIVE_TRANSITION_CLOSURE_STEM,
        state.authoritative_transition_closure_rows,
        AUTHORITATIVE_TRANSITION_CLOSURE_FIELDS,
    )
    for name in excluded_job_names or set():
        jobs.pop(name, None)
    with suppress_feature_json_outputs():
        paths = publish_feature_triplets(
            step_root=final_step_root,
            jobs=jobs,
            max_workers=_FINAL_PUBLISH_WORKERS,
        )
    if state.publish_topology_connectivity_json:
        topology_path = final_step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
        _write_deferred_feature_json(
            final_step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.json",
            read_features(topology_path) if topology_path.is_file() else state.topology_connectivity_audit_rows,
        )
    if state.authoritative_transition_closure_rows:
        _write_deferred_feature_json(
            final_step_root / f"{AUTHORITATIVE_TRANSITION_CLOSURE_STEM}.json",
            state.authoritative_transition_closure_rows,
        )
    return paths


def _fieldnames(state: Step3SurfaceRuntimeState, job_name: str) -> list[str]:
    fieldnames = state.deferred_publish_fieldnames.get(job_name)
    if fieldnames:
        return fieldnames
    rows = state.frcsd_roads if job_name == "road" else state.frcsd_nodes
    result: list[str] = []
    for row in rows:
        for field_name in (row.get("properties") or {}):
            if field_name not in result:
                result.append(str(field_name))
    return result


def _write_deferred_feature_json(path: Path, rows: list[dict[str, Any]]) -> None:
    write_json(
        path,
        {
            "row_count": len(rows),
            "features": [_feature_json(row) for row in rows],
        },
    )
