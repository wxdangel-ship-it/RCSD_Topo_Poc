#!/usr/bin/env python3
"""Compare semantic path alias transitions with standard intersection surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.candidate_audit import (
    audit_frcsd_candidates,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    build_node_context,
    field_name,
    normalize_id,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import load_inputs
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import AuditConfig


def _path_from_manifest(payload: Mapping[str, Any], key: str) -> Path | None:
    row = payload.get("inputs", {}).get(key)
    if not isinstance(row, Mapping):
        return None
    value = str(row.get("path") or "").strip()
    return Path(value).resolve() if value else None


def _infer_t06_root(t05_anchor_audit: Path) -> Path:
    case_root = t05_anchor_audit.parents[2]
    candidate = case_root / "t06_step12" / "t06"
    if not candidate.is_dir():
        raise RuntimeError(f"cannot infer T06 root from {t05_anchor_audit}")
    return candidate.resolve()


def _load_run(run_root: Path) -> tuple[list[dict[str, Any]], Any]:
    manifest = json.loads(
        (run_root / "t12_frcsd_quality_audit_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    params = dict(manifest.get("parameters") or {})
    config = AuditConfig(**params)
    t05_anchor_audit = _path_from_manifest(manifest, "t05_anchor_audit")
    if t05_anchor_audit is None:
        raise RuntimeError(f"missing t05_anchor_audit in {run_root}")
    loaded = load_inputs(
        swsd_segment_path=_path_from_manifest(manifest, "swsd_segment"),
        swsd_roads_path=_path_from_manifest(manifest, "swsd_roads"),
        swsd_nodes_path=_path_from_manifest(manifest, "swsd_nodes"),
        frcsd_roads_path=_path_from_manifest(manifest, "frcsd_roads"),
        frcsd_nodes_path=_path_from_manifest(manifest, "frcsd_nodes"),
        t05_anchor_audit_path=t05_anchor_audit,
        rcsd_intersection_path=_path_from_manifest(manifest, "rcsd_intersection"),
        t06_run_root=_infer_t06_root(t05_anchor_audit),
        drivezone_path=_path_from_manifest(manifest, "drivezone"),
        case_manifest_path=_path_from_manifest(manifest, "case_manifest"),
        config=config,
    )
    candidates, _, _ = audit_frcsd_candidates(loaded, config)
    return candidates, loaded


def _selected_ids(run_root: Path, configured: set[str]) -> set[str]:
    if configured:
        return configured
    path = run_root / "t12_frcsd_confirmed_quality_issues.csv"
    frame = pd.read_csv(path, dtype=str).fillna("")
    return set(frame[field_name(frame, "candidate_id")].map(normalize_id))


def _road_map(roads: pd.DataFrame) -> tuple[dict[str, Any], dict[str, str]]:
    fields = {
        name: field_name(roads, name)
        for name in ("id", "snodeid", "enodeid")
    }
    return (
        {
            normalize_id(row[fields["id"]]): row
            for _, row in roads.iterrows()
        },
        fields,
    )


def _raw_endpoint_for_canonical(
    road: Any,
    canonical_id: str,
    fields: Mapping[str, str],
    canonicalizer: Any,
) -> str:
    for name in ("snodeid", "enodeid"):
        raw_id = normalize_id(road[fields[name]])
        if canonicalizer.canonicalize(raw_id) == canonical_id:
            return raw_id
    return ""


def _surface_indexes(point: Any, intersections: Any, tolerance_m: float) -> set[int]:
    if point is None or point.is_empty or intersections.empty:
        return set()
    query = point.buffer(tolerance_m)
    indexes = intersections.sindex.query(query, predicate="intersects")
    return {
        int(position)
        for position in indexes
        if float(intersections.iloc[int(position)].geometry.distance(point))
        <= tolerance_m
    }


def _transition_rows(
    *,
    run_id: str,
    candidate_id: str,
    direction: str,
    path_kind: str,
    road_ids: list[str],
    road_map: Mapping[str, Any],
    fields: Mapping[str, str],
    canonicalizer: Any,
    node_points: Mapping[str, Any],
    intersections: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sequence, (left_id, right_id) in enumerate(
        zip(road_ids, road_ids[1:]),
        start=1,
    ):
        left = road_map[left_id]
        right = road_map[right_id]
        left_canonical = {
            canonicalizer.canonicalize(normalize_id(left[fields[name]]))
            for name in ("snodeid", "enodeid")
        }
        right_canonical = {
            canonicalizer.canonicalize(normalize_id(right[fields[name]]))
            for name in ("snodeid", "enodeid")
        }
        shared = sorted(left_canonical & right_canonical)
        canonical_id = shared[0] if len(shared) == 1 else ""
        left_raw = (
            _raw_endpoint_for_canonical(left, canonical_id, fields, canonicalizer)
            if canonical_id
            else ""
        )
        right_raw = (
            _raw_endpoint_for_canonical(right, canonical_id, fields, canonicalizer)
            if canonical_id
            else ""
        )
        left_point = node_points.get(left_raw)
        right_point = node_points.get(right_raw)
        gap = (
            float(left_point.distance(right_point))
            if left_point is not None and right_point is not None
            else None
        )
        left_surfaces = _surface_indexes(left_point, intersections, 1.0)
        right_surfaces = _surface_indexes(right_point, intersections, 1.0)
        shared_surfaces = left_surfaces & right_surfaces
        alias_transition = bool(left_raw and right_raw and left_raw != right_raw)
        rows.append(
            {
                "run_id": run_id,
                "candidate_id": candidate_id,
                "direction": direction,
                "path_kind": path_kind,
                "sequence": sequence,
                "left_road_id": left_id,
                "right_road_id": right_id,
                "canonical_id": canonical_id,
                "left_raw_node_id": left_raw,
                "right_raw_node_id": right_raw,
                "alias_transition": alias_transition,
                "raw_node_gap_m": gap,
                "shared_standard_surface": bool(shared_surfaces),
                "shared_standard_surface_count": len(shared_surfaces),
                "transition_interpretable": bool(
                    canonical_id
                    and left_raw
                    and right_raw
                    and (left_raw == right_raw or shared_surfaces)
                ),
            }
        )
    return rows


def _semantic_endpoint_evidence(
    *,
    metrics: Mapping[str, Any],
    road_ids: list[str],
    road_map: Mapping[str, Any],
    fields: Mapping[str, str],
    canonicalizer: Any,
    node_points: Mapping[str, Any],
    start_portals: list[Mapping[str, Any]],
    end_portals: list[Mapping[str, Any]],
    intersections: Any,
) -> dict[str, Any]:
    if not road_ids:
        return {
            "semantic_start_raw_node": "",
            "semantic_end_raw_node": "",
            "start_portal_exact": False,
            "end_portal_exact": False,
            "start_portal_min_gap_m": None,
            "end_portal_min_gap_m": None,
            "start_portal_shared_surface": False,
            "end_portal_shared_surface": False,
        }
    start_canonical = normalize_id(metrics.get("start_portal"))
    end_canonical = normalize_id(metrics.get("end_portal"))
    start_raw = _raw_endpoint_for_canonical(
        road_map[road_ids[0]],
        start_canonical,
        fields,
        canonicalizer,
    )
    end_raw = _raw_endpoint_for_canonical(
        road_map[road_ids[-1]],
        end_canonical,
        fields,
        canonicalizer,
    )

    def compare(raw_id: str, portals: list[Mapping[str, Any]]) -> tuple[Any, ...]:
        portal_ids = {normalize_id(row.get("raw_id")) for row in portals}
        point = node_points.get(raw_id)
        portal_points = [
            node_points.get(portal_id)
            for portal_id in portal_ids
            if node_points.get(portal_id) is not None
        ]
        min_gap = (
            min(float(point.distance(portal_point)) for portal_point in portal_points)
            if point is not None and portal_points
            else None
        )
        point_surfaces = _surface_indexes(point, intersections, 1.0)
        shared_surface = any(
            bool(point_surfaces & _surface_indexes(portal_point, intersections, 1.0))
            for portal_point in portal_points
        )
        return raw_id in portal_ids, min_gap, shared_surface

    start_exact, start_gap, start_surface = compare(start_raw, start_portals)
    end_exact, end_gap, end_surface = compare(end_raw, end_portals)
    return {
        "semantic_start_raw_node": start_raw,
        "semantic_end_raw_node": end_raw,
        "start_portal_exact": start_exact,
        "end_portal_exact": end_exact,
        "start_portal_min_gap_m": start_gap,
        "end_portal_min_gap_m": end_gap,
        "start_portal_shared_surface": start_surface,
        "end_portal_shared_surface": end_surface,
    }


def _audit_run(
    run_root: Path,
    configured_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates, loaded = _load_run(run_root)
    selected = _selected_ids(run_root, configured_ids)
    canonicalizer, _, node_points = build_node_context(loaded.frcsd_nodes)
    roads, fields = _road_map(loaded.frcsd_roads)
    transition_rows: list[dict[str, Any]] = []
    direction_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = normalize_id(candidate["candidate_id"])
        if candidate_id not in selected:
            continue
        for direction in candidate["directions"]:
            direction_name = str(direction["direction"])
            for path_kind in (
                "semantic_local_directed",
                "semantic_full_directed",
                "semantic_local_undirected",
                "semantic_full_undirected",
            ):
                metrics = direction[path_kind]
                rows = _transition_rows(
                    run_id=run_root.name,
                    candidate_id=candidate_id,
                    direction=direction_name,
                    path_kind=path_kind,
                    road_ids=list(metrics.get("road_ids") or []),
                    road_map=roads,
                    fields=fields,
                    canonicalizer=canonicalizer,
                    node_points=node_points,
                    intersections=loaded.rcsd_intersections,
                )
                transition_rows.extend(rows)
                aliases = [row for row in rows if row["alias_transition"]]
                endpoint_evidence = _semantic_endpoint_evidence(
                    metrics=metrics,
                    road_ids=list(metrics.get("road_ids") or []),
                    road_map=roads,
                    fields=fields,
                    canonicalizer=canonicalizer,
                    node_points=node_points,
                    start_portals=direction["start_portal_candidates"],
                    end_portals=direction["end_portal_candidates"],
                    intersections=loaded.rcsd_intersections,
                )
                direction_rows.append(
                    {
                        "run_id": run_root.name,
                        "candidate_id": candidate_id,
                        "direction": direction_name,
                        "path_kind": path_kind,
                        "path_exists": bool(metrics.get("exists")),
                        "path_accepted": bool(
                            metrics.get("accepted_equivalent_carrier")
                        ),
                        "road_count": len(metrics.get("road_ids") or []),
                        "transition_count": len(rows),
                        "alias_transition_count": len(aliases),
                        "surface_supported_alias_count": sum(
                            bool(row["shared_standard_surface"]) for row in aliases
                        ),
                        "unsupported_alias_count": sum(
                            not bool(row["transition_interpretable"])
                            for row in aliases
                        ),
                        "max_alias_gap_m": max(
                            (
                                float(row["raw_node_gap_m"])
                                for row in aliases
                                if row["raw_node_gap_m"] is not None
                            ),
                            default=0.0,
                        ),
                        **endpoint_evidence,
                    }
                )
    return direction_rows, transition_rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", action="append", type=Path, default=[])
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--selection-csv", type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args(argv)

    run_roots = [path.resolve() for path in args.run_root]
    if args.runs_root is not None:
        run_roots.extend(
            sorted(
                path.resolve()
                for path in args.runs_root.resolve().iterdir()
                if path.is_dir()
                and (path / "t12_frcsd_quality_audit_manifest.json").is_file()
            )
        )
    if not run_roots:
        raise RuntimeError("at least one T12 run root is required")
    selected: set[str] = set()
    if args.selection_csv is not None:
        frame = pd.read_csv(args.selection_csv, dtype=str).fillna("")
        selected = set(frame[field_name(frame, "segment_id")].map(normalize_id))

    direction_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    for run_root in run_roots:
        directions, transitions = _audit_run(run_root, selected)
        direction_rows.extend(directions)
        transition_rows.extend(transitions)

    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    direction_path = out_root / "semantic_path_transition_summary.csv"
    transition_path = out_root / "semantic_path_transitions.csv"
    summary_path = out_root / "semantic_path_transition_summary.json"
    pd.DataFrame(direction_rows).to_csv(
        direction_path,
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(transition_rows).to_csv(
        transition_path,
        index=False,
        encoding="utf-8-sig",
    )
    payload = {
        "run_count": len(run_roots),
        "candidate_count": len({row["candidate_id"] for row in direction_rows}),
        "direction_path_count": len(direction_rows),
        "transition_count": len(transition_rows),
        "alias_transition_count": sum(
            bool(row["alias_transition"]) for row in transition_rows
        ),
        "unsupported_alias_transition_count": sum(
            bool(row["alias_transition"])
            and not bool(row["transition_interpretable"])
            for row in transition_rows
        ),
        "direction_summary_csv": str(direction_path),
        "transition_csv": str(transition_path),
    }
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"summary": str(summary_path), **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
