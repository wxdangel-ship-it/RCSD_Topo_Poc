from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .fusion import fuse_surfaces
from .io import prepare_run_root, produced_at_utc, read_surfaces
from .models import (
    SOURCE_T02_INPUT,
    SOURCE_T03,
    SOURCE_T04,
    TARGET_CRS_TEXT,
    T05Phase1Artifacts,
)
from .normalizer import (
    NodeLookup,
    normalize_t02_input,
    normalize_t03_surfaces,
    normalize_t04_surfaces,
)
from .outputs import write_t05_outputs


def run_t05_junction_surface_fusion(
    *,
    t02_rcsdintersection_path: str | Path,
    t03_surface_path: str | Path | None,
    t04_surface_path: str | Path | None,
    nodes_path: str | Path | None,
    out_root: str | Path,
    run_id: str | None = None,
    t02_layer: str | None = None,
    t03_layer: str | None = None,
    t04_layer: str | None = None,
    nodes_layer: str | None = None,
    t02_crs: str | None = None,
    t03_crs: str | None = None,
    t04_crs: str | None = None,
    nodes_crs: str | None = None,
) -> T05Phase1Artifacts:
    run_root = prepare_run_root(out_root, run_id)
    produced_at = produced_at_utc()

    nodes_lookup = NodeLookup.empty()
    if nodes_path is not None:
        nodes_layer_result = read_surfaces(nodes_path, layer_name=nodes_layer, crs_override=nodes_crs)
        nodes_lookup = NodeLookup.from_features(nodes_layer_result.features)

    input_counts: Counter[str] = Counter()
    skipped_rows: list[dict[str, Any]] = []

    t02_layer_result = read_surfaces(
        t02_rcsdintersection_path,
        layer_name=t02_layer,
        crs_override=t02_crs,
    )
    t02_surfaces, t02_skipped = normalize_t02_input(t02_layer_result.features, nodes=nodes_lookup)
    input_counts[SOURCE_T02_INPUT] = len(t02_surfaces)
    skipped_rows.extend(t02_skipped)

    all_surfaces = list(t02_surfaces)
    if t03_surface_path is not None:
        t03_layer_result = read_surfaces(t03_surface_path, layer_name=t03_layer, crs_override=t03_crs)
        t03_surfaces, t03_skipped = normalize_t03_surfaces(t03_layer_result.features, nodes=nodes_lookup)
        input_counts[SOURCE_T03] = len(t03_surfaces)
        skipped_rows.extend(t03_skipped)
        all_surfaces.extend(t03_surfaces)
    else:
        input_counts[SOURCE_T03] = 0

    if t04_surface_path is not None:
        t04_layer_result = read_surfaces(t04_surface_path, layer_name=t04_layer, crs_override=t04_crs)
        t04_surfaces, t04_skipped = normalize_t04_surfaces(t04_layer_result.features, nodes=nodes_lookup)
        input_counts[SOURCE_T04] = len(t04_surfaces)
        skipped_rows.extend(t04_skipped)
        all_surfaces.extend(t04_surfaces)
    else:
        input_counts[SOURCE_T04] = 0

    fusion_results = fuse_surfaces(all_surfaces)
    audit_rows = [result.audit_row for result in fusion_results]
    surface_rows = [
        result.surface_feature.get("properties") or {}
        for result in fusion_results
        if result.surface_feature is not None
    ]

    summary_base = _summary_base(
        produced_at=produced_at,
        run_id=run_root.name,
        input_paths={
            "t02_rcsdintersection_path": str(t02_rcsdintersection_path),
            "t03_surface_path": str(t03_surface_path) if t03_surface_path is not None else None,
            "t04_surface_path": str(t04_surface_path) if t04_surface_path is not None else None,
            "nodes_path": str(nodes_path) if nodes_path is not None else None,
        },
        input_counts=input_counts,
        skipped_count=len(skipped_rows),
        audit_rows=audit_rows,
        surface_rows=surface_rows,
    )
    paths = write_t05_outputs(
        run_root=run_root,
        fusion_results=fusion_results,
        skipped_rows=skipped_rows,
        summary_base=summary_base,
    )
    return T05Phase1Artifacts(
        run_root=run_root,
        surface_path=paths["surface_path"],
        audit_csv_path=paths["audit_csv_path"],
        audit_json_path=paths["audit_json_path"],
        summary_path=paths["summary_path"],
        skipped_csv_path=paths["skipped_csv_path"],
        skipped_json_path=paths["skipped_json_path"],
        published_surface_count=summary_base["published_surface_count"],
        conflict_count=summary_base["conflict_count"],
        skipped_count=len(skipped_rows),
    )


def _summary_base(
    *,
    produced_at: str,
    run_id: str,
    input_paths: dict[str, Any],
    input_counts: Counter[str],
    skipped_count: int,
    audit_rows: list[dict[str, Any]],
    surface_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    conflict_count = sum(1 for row in audit_rows if row.get("conflict_state") not in ("", None, "none"))
    multi_source_surface_count = sum(1 for row in surface_rows if row.get("is_multi_source_merged") == 1)
    published_surface_count = len(surface_rows)
    return {
        "run_id": run_id,
        "produced_at": produced_at,
        "input_paths": input_paths,
        "total_input_surface_count": sum(input_counts.values()),
        "t02_input_count": input_counts[SOURCE_T02_INPUT],
        "t03_input_count": input_counts[SOURCE_T03],
        "t04_input_count": input_counts[SOURCE_T04],
        "published_surface_count": published_surface_count,
        "single_source_surface_count": published_surface_count - multi_source_surface_count,
        "multi_source_surface_count": multi_source_surface_count,
        "conflict_count": conflict_count,
        "skipped_count": skipped_count,
        "missing_mainnodeid_count": sum(1 for row in surface_rows if not str(row.get("mainnodeid") or "").strip()),
        "missing_patch_id_count": sum(1 for row in surface_rows if not str(row.get("patch_id") or "").strip()),
        "missing_kind_2_count": sum(1 for row in surface_rows if row.get("kind_2") in (None, "")),
        "crs": TARGET_CRS_TEXT,
    }
