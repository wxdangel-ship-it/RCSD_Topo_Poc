#!/usr/bin/env python3
"""Audit directed carrier prefixes that approach a trusted T07 surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.anchor_portals import (
    associate_t07_surfaces,
    build_anchor_map,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.candidate_audit import (
    audit_frcsd_candidates,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    PathResult,
    build_graph,
    build_node_context,
    field_name,
    normalize_id,
    path_metrics,
    shortest_path_between_sets,
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
    candidate = t05_anchor_audit.parents[2] / "t06_step12" / "t06"
    if not candidate.is_dir():
        raise RuntimeError(f"cannot infer T06 root from {t05_anchor_audit}")
    return candidate.resolve()


def _load_run(run_root: Path) -> tuple[list[dict[str, Any]], Any, AuditConfig]:
    manifest = json.loads(
        (run_root / "t12_frcsd_quality_audit_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    config = AuditConfig(**dict(manifest.get("parameters") or {}))
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
    return candidates, loaded, config


def _append_transition(
    prefix: PathResult | None,
    *,
    start: str,
    end: str,
    road_id: str,
    edge_length: float,
) -> PathResult:
    if prefix is None:
        return PathResult(
            start=start,
            end=end,
            node_ids=(start, end),
            road_ids=(road_id,),
            length_m=edge_length,
        )
    return PathResult(
        start=prefix.start,
        end=end,
        node_ids=(*prefix.node_ids, end),
        road_ids=(*prefix.road_ids, road_id),
        length_m=prefix.length_m + edge_length,
    )


def _surface_prefixes(
    *,
    graph: Any,
    starts: set[str],
    surface: Any,
    target_point: Any,
    reference_geometry: Any,
    reference_length_m: float,
    config: AuditConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start_node, transitions in graph.directed.items():
        prefix = shortest_path_between_sets(graph.directed, starts, [start_node])
        if prefix is None and start_node not in starts:
            continue
        for end_node, road_id, edge_length in transitions:
            if prefix is not None and road_id in prefix.road_ids:
                continue
            path = _append_transition(
                prefix,
                start=start_node,
                end=end_node,
                road_id=road_id,
                edge_length=float(edge_length),
            )
            metrics = path_metrics(
                path,
                graph.edges,
                reference_geometry,
                reference_length_m,
                config,
            )
            edge = graph.edges[road_id]
            rows.append(
                {
                    "terminal_road_id": road_id,
                    "terminal_start_node": start_node,
                    "terminal_end_node": end_node,
                    "road_ids": list(path.road_ids),
                    "road_count": len(path.road_ids),
                    "path_length_m": metrics["length_m"],
                    "path_length_ratio": metrics["length_ratio"],
                    "max_corridor_distance_m": metrics[
                        "max_corridor_distance_m"
                    ],
                    "path_geometry_accepted": bool(
                        metrics["accepted_equivalent_carrier"]
                    ),
                    "terminal_road_surface_gap_m": float(
                        edge.geometry.distance(surface)
                    ),
                    "terminal_road_swsd_portal_gap_m": float(
                        edge.geometry.distance(target_point)
                    ),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            not row["path_geometry_accepted"],
            row["terminal_road_surface_gap_m"],
            row["terminal_road_swsd_portal_gap_m"],
            row["path_length_m"],
            row["terminal_road_id"],
        ),
    )


def _surface_to_surface_paths(
    *,
    graph: Any,
    source_surface: Any,
    target_surface: Any,
    source_point: Any,
    target_point: Any,
    reference_geometry: Any,
    reference_length_m: float,
    config: AuditConfig,
) -> list[dict[str, Any]]:
    transitions = [
        (start, end, road_id, float(edge_length))
        for start, edges in graph.directed.items()
        for end, road_id, edge_length in edges
    ]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for start_node, after_start, start_road, start_length in transitions:
        for before_end, end_node, end_road, end_length in transitions:
            if start_road == end_road:
                path = PathResult(
                    start=start_node,
                    end=after_start,
                    node_ids=(start_node, after_start),
                    road_ids=(start_road,),
                    length_m=start_length,
                )
            else:
                middle = shortest_path_between_sets(
                    graph.directed,
                    [after_start],
                    [before_end],
                )
                if middle is None:
                    continue
                road_ids = (start_road, *middle.road_ids, end_road)
                if len(set(road_ids)) != len(road_ids):
                    continue
                path = PathResult(
                    start=start_node,
                    end=end_node,
                    node_ids=(start_node, *middle.node_ids, end_node),
                    road_ids=road_ids,
                    length_m=start_length + middle.length_m + end_length,
                )
            if path.road_ids in seen:
                continue
            seen.add(path.road_ids)
            metrics = path_metrics(
                path,
                graph.edges,
                reference_geometry,
                reference_length_m,
                config,
            )
            first = graph.edges[path.road_ids[0]]
            last = graph.edges[path.road_ids[-1]]
            rows.append(
                {
                    "source_road_id": path.road_ids[0],
                    "terminal_road_id": path.road_ids[-1],
                    "road_ids": list(path.road_ids),
                    "road_count": len(path.road_ids),
                    "path_length_m": metrics["length_m"],
                    "path_length_ratio": metrics["length_ratio"],
                    "max_corridor_distance_m": metrics[
                        "max_corridor_distance_m"
                    ],
                    "path_geometry_accepted": bool(
                        metrics["accepted_equivalent_carrier"]
                    ),
                    "source_road_surface_gap_m": float(
                        first.geometry.distance(source_surface)
                    ),
                    "source_road_swsd_portal_gap_m": float(
                        first.geometry.distance(source_point)
                    ),
                    "terminal_road_surface_gap_m": float(
                        last.geometry.distance(target_surface)
                    ),
                    "terminal_road_swsd_portal_gap_m": float(
                        last.geometry.distance(target_point)
                    ),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            not row["path_geometry_accepted"],
            row["source_road_surface_gap_m"]
            + row["terminal_road_surface_gap_m"],
            row["source_road_swsd_portal_gap_m"]
            + row["terminal_road_swsd_portal_gap_m"],
            abs(float(row["path_length_ratio"]) - 1.0),
            row["road_ids"],
        ),
    )


def _audit_run(run_root: Path) -> list[dict[str, Any]]:
    candidates, loaded, config = _load_run(run_root)
    anchors = build_anchor_map(loaded.t05_anchor_audit)
    swsd_canonicalizer, _, swsd_points = build_node_context(loaded.swsd_nodes)
    frcsd_canonicalizer, _, _ = build_node_context(loaded.frcsd_nodes)
    t07_surfaces, _ = associate_t07_surfaces(
        anchors,
        swsd_points,
        loaded.rcsd_intersections,
        tolerance_m=config.portal_radius_m,
    )
    segment_id_field = field_name(loaded.segments, "id")
    pair_field = field_name(loaded.segments, "pair_nodes")
    road_field = field_name(loaded.segments, "roads")
    swsd_road_id_field = field_name(loaded.swsd_roads, "id")
    swsd_ids = loaded.swsd_roads[swsd_road_id_field].map(normalize_id)
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = normalize_id(candidate["candidate_id"])
        segment = loaded.segments.loc[
            loaded.segments[segment_id_field].map(normalize_id) == candidate_id
        ].iloc[0]
        pair_nodes = [
            normalize_id(value)
            for value in str(segment[pair_field]).replace("|", ",").split(",")
            if normalize_id(value)
        ]
        road_ids = {
            normalize_id(value)
            for value in str(segment[road_field]).replace("|", ",").split(",")
            if normalize_id(value)
        }
        segment_roads = loaded.swsd_roads.loc[swsd_ids.isin(road_ids)].copy()
        local_roads = loaded.frcsd_roads.loc[
            loaded.frcsd_roads.geometry.intersects(
                segment.geometry.buffer(config.local_corridor_m)
            )
        ].copy()
        graph = build_graph(local_roads, frcsd_canonicalizer)
        for evidence in candidate["directions"]:
            direction = str(evidence["direction"])
            if direction not in candidate["failed_directions"]:
                continue
            source_index, target_index = (
                (0, 1) if direction == "pair0_to_pair1" else (1, 0)
            )
            source_pair = pair_nodes[source_index]
            target_pair = pair_nodes[target_index]
            source_surface = t07_surfaces.get(source_pair)
            surface = t07_surfaces.get(target_pair)
            source_swsd_raw = normalize_id(evidence["source_swsd_portal"])
            target_swsd_raw = normalize_id(evidence["target_swsd_portal"])
            source_point = swsd_points.get(source_swsd_raw)
            target_point = swsd_points.get(target_swsd_raw)
            if (
                source_surface is None
                or surface is None
                or source_point is None
                or target_point is None
            ):
                output.append(
                    {
                        "run_id": run_root.name,
                        "candidate_id": candidate_id,
                        "direction": direction,
                        "status": "not_assessable",
                        "reason": "target_surface_or_swsd_portal_missing",
                    }
                )
                continue
            for role, role_surface, role_point in (
                ("source", source_surface, source_point),
                ("target", surface, target_point),
            ):
                ranked_roads = sorted(
                    graph.edges.values(),
                    key=lambda edge: (
                        float(edge.geometry.distance(role_surface)),
                        float(edge.geometry.distance(role_point)),
                        edge.road_id,
                    ),
                )
                for rank, edge in enumerate(ranked_roads[:10], start=1):
                    output.append(
                        {
                            "run_id": run_root.name,
                            "candidate_id": candidate_id,
                            "direction": direction,
                            "status": "local_road_surface_rank",
                            "role": role,
                            "rank": rank,
                            "terminal_road_id": edge.road_id,
                            "terminal_start_node": edge.start,
                            "terminal_end_node": edge.end,
                            "terminal_road_surface_gap_m": float(
                                edge.geometry.distance(role_surface)
                            ),
                            "terminal_road_swsd_portal_gap_m": float(
                                edge.geometry.distance(role_point)
                            ),
                        }
                    )
            starts = {
                frcsd_canonicalizer.canonicalize(row["raw_id"])
                for row in evidence["start_portal_candidates"]
            }
            prefixes = _surface_prefixes(
                graph=graph,
                starts=starts,
                surface=surface,
                target_point=target_point,
                reference_geometry=segment.geometry,
                reference_length_m=float(evidence["swsd_length_m"]),
                config=config,
            )
            for rank, row in enumerate(prefixes[:10], start=1):
                output.append(
                    {
                        "run_id": run_root.name,
                        "candidate_id": candidate_id,
                        "direction": direction,
                        "status": "ranked_prefix",
                        "rank": rank,
                        "target_pair_id": target_pair,
                        "target_swsd_portal": target_swsd_raw,
                        **row,
                    }
                )
            surface_paths = _surface_to_surface_paths(
                graph=graph,
                source_surface=source_surface,
                target_surface=surface,
                source_point=source_point,
                target_point=target_point,
                reference_geometry=segment.geometry,
                reference_length_m=float(evidence["swsd_length_m"]),
                config=config,
            )
            for rank, row in enumerate(surface_paths[:20], start=1):
                output.append(
                    {
                        "run_id": run_root.name,
                        "candidate_id": candidate_id,
                        "direction": direction,
                        "status": "surface_to_surface_path",
                        "rank": rank,
                        **row,
                    }
                )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", action="append", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args(argv)

    rows: list[dict[str, Any]] = []
    for run_root in args.run_root:
        rows.extend(_audit_run(run_root.resolve()))
    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    csv_path = out_root / "anchored_surface_portal_prefixes.csv"
    json_path = out_root / "anchored_surface_portal_prefixes.json"
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"row_count": len(rows), "csv": str(csv_path), "json": str(json_path)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
