#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from rcsd_topo_poc.modules.t12_frcsd_quality_audit import (
    AuditConfig,
    T12ContractError,
    run_t12_frcsd_quality_audit,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit original 1V1 FRCSD traversability against SWSD Segments."
    )
    parser.add_argument("--swsd-segment", required=True, type=Path)
    parser.add_argument("--swsd-roads", required=True, type=Path)
    parser.add_argument("--swsd-nodes", required=True, type=Path)
    parser.add_argument("--frcsd-roads", required=True, type=Path)
    parser.add_argument("--frcsd-nodes", required=True, type=Path)
    parser.add_argument("--t05-anchor-audit", required=True, type=Path)
    parser.add_argument("--rcsd-intersection", required=True, type=Path)
    parser.add_argument("--t06-run-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--drivezone", type=Path)
    parser.add_argument("--case-manifest", type=Path)
    parser.add_argument("--review-decisions", type=Path)
    parser.add_argument("--processing-crs")
    parser.add_argument("--local-corridor-m", type=float, default=50.0)
    parser.add_argument("--portal-radius-m", type=float, default=50.0)
    parser.add_argument("--crop-inner-margin-m", type=float, default=500.0)
    parser.add_argument("--path-max-length-ratio", type=float, default=1.5)
    parser.add_argument("--path-max-additive-m", type=float, default=100.0)
    parser.add_argument("--path-max-corridor-distance-m", type=float, default=50.0)
    parser.add_argument("--sample-spacing-m", type=float, default=5.0)
    parser.add_argument("--allow-unverified-t06-evidence", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args(argv)
    config = AuditConfig(
        local_corridor_m=args.local_corridor_m,
        portal_radius_m=args.portal_radius_m,
        crop_inner_margin_m=args.crop_inner_margin_m,
        path_max_length_ratio=args.path_max_length_ratio,
        path_max_additive_m=args.path_max_additive_m,
        path_max_corridor_distance_m=args.path_max_corridor_distance_m,
        sample_spacing_m=args.sample_spacing_m,
        processing_crs=args.processing_crs,
        allow_unverified_t06_evidence=args.allow_unverified_t06_evidence,
    )
    try:
        artifacts = run_t12_frcsd_quality_audit(
            swsd_segment_path=args.swsd_segment,
            swsd_roads_path=args.swsd_roads,
            swsd_nodes_path=args.swsd_nodes,
            frcsd_roads_path=args.frcsd_roads,
            frcsd_nodes_path=args.frcsd_nodes,
            t05_anchor_audit_path=args.t05_anchor_audit,
            rcsd_intersection_path=args.rcsd_intersection,
            t06_run_root=args.t06_run_root,
            out_root=args.out_root,
            run_id=args.run_id,
            drivezone_path=args.drivezone,
            case_manifest_path=args.case_manifest,
            review_decisions_path=args.review_decisions,
            config=config,
            progress=args.progress,
        )
    except T12ContractError as exc:
        parser.exit(2, f"[T12 BLOCKED] {exc}\n")
    payload = {
        "run_root": str(artifacts.run_root),
        "manifest_json": str(artifacts.manifest_json),
        "summary_json": str(artifacts.summary_json),
        "candidate_count": artifacts.candidate_count,
        "confirmed_count": artifacts.confirmed_count,
        "exclusion_count": artifacts.exclusion_count,
        "manual_review_count": artifacts.manual_review_count,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
