from __future__ import annotations

import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import shapely

from .candidate_audit import audit_frcsd_candidates
from .inputs import load_inputs
from .models import AuditConfig, T12Artifacts, T12ContractError
from .outputs import write_failure_manifest, write_outputs
from .review_publish import apply_review_decisions


def run_t12_frcsd_quality_audit(
    *,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    frcsd_roads_path: str | Path,
    frcsd_nodes_path: str | Path,
    t05_anchor_audit_path: str | Path,
    rcsd_intersection_path: str | Path,
    t06_run_root: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    drivezone_path: str | Path | None = None,
    case_manifest_path: str | Path | None = None,
    review_decisions_path: str | Path | None = None,
    config: AuditConfig | None = None,
    progress: bool = False,
) -> T12Artifacts:
    active_config = config or AuditConfig()
    active_config.validate()
    active_run_id = run_id or _default_run_id()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", active_run_id):
        raise T12ContractError(f"invalid run_id: {active_run_id}")
    output_root = Path(out_root).resolve() / active_run_id
    if output_root.exists():
        raise T12ContractError(
            "output run root already exists; choose a new run_id to avoid overwrite: "
            f"{output_root}"
        )
    stage_elapsed: dict[str, float] = {}
    try:
        _progress(progress, "load_inputs")
        stage_start = time.perf_counter()
        loaded = load_inputs(
            swsd_segment_path=Path(swsd_segment_path),
            swsd_roads_path=Path(swsd_roads_path),
            swsd_nodes_path=Path(swsd_nodes_path),
            frcsd_roads_path=Path(frcsd_roads_path),
            frcsd_nodes_path=Path(frcsd_nodes_path),
            t05_anchor_audit_path=Path(t05_anchor_audit_path),
            rcsd_intersection_path=Path(rcsd_intersection_path),
            t06_run_root=Path(t06_run_root),
            drivezone_path=Path(drivezone_path) if drivezone_path else None,
            case_manifest_path=Path(case_manifest_path) if case_manifest_path else None,
            config=active_config,
        )
        stage_elapsed["loading_and_preflight"] = time.perf_counter() - stage_start
        _progress(progress, "audit_candidates")
        stage_start = time.perf_counter()
        candidates, layers, candidate_audit = audit_frcsd_candidates(
            loaded,
            active_config,
        )
        stage_elapsed["candidate_audit"] = time.perf_counter() - stage_start
        _progress(progress, "apply_review")
        stage_start = time.perf_counter()
        reviewed, confirmed, exclusions, manual = apply_review_decisions(
            candidates,
            run_id=active_run_id,
            review_decisions_path=(
                Path(review_decisions_path) if review_decisions_path else None
            ),
        )
        stage_elapsed["review_publish"] = time.perf_counter() - stage_start
        _progress(progress, "write_outputs")
        runtime = {
            "platform": platform.platform(),
            "python": sys.version,
            "geopandas": gpd.__version__,
            "shapely": shapely.__version__,
            "object_counts": {
                "segment_count": len(loaded.segments),
                "frcsd_road_count": len(loaded.frcsd_roads),
                "frcsd_node_count": len(loaded.frcsd_nodes),
            },
            "stage_elapsed_seconds": stage_elapsed,
        }
        artifacts = write_outputs(
            run_root=output_root,
            run_id=active_run_id,
            processing_crs=loaded.processing_crs,
            config=active_config,
            candidates=candidates,
            reviewed=reviewed,
            confirmed=confirmed,
            exclusions=exclusions,
            manual=manual,
            layers=layers,
            input_audit=loaded.input_audit,
            topology_audit=loaded.topology_audit,
            evidence_audit=loaded.evidence_audit,
            candidate_audit=candidate_audit,
            runtime=runtime,
        )
        return artifacts
    except T12ContractError as exc:
        write_failure_manifest(
            output_root,
            run_id=active_run_id,
            status="blocked",
            error=exc,
            config=active_config,
        )
        raise
    except Exception as exc:
        write_failure_manifest(
            output_root,
            run_id=active_run_id,
            status="failed",
            error=exc,
            config=active_config,
        )
        raise


def _default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"t12_frcsd_quality_audit_{stamp}"


def _progress(enabled: bool, stage: str) -> None:
    if enabled:
        print(f"[T12] stage={stage}", flush=True)
