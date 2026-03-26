from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_json, write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import SemanticNodeRecord, _sort_key


ENDPOINT_POOL_CSV_NAME = "endpoint_pool.csv"
ENDPOINT_POOL_SUMMARY_NAME = "endpoint_pool_summary.json"
ENDPOINT_POOL_NODES_NAME = "endpoint_pool_nodes.gpkg"


def build_endpoint_pool_source_map(
    *,
    node_ids: set[str],
    stage_id: str,
    previous_source_map: Optional[dict[str, tuple[str, ...]]] = None,
) -> dict[str, tuple[str, ...]]:
    previous_source_map = previous_source_map or {}
    source_map: dict[str, tuple[str, ...]] = {}
    for node_id in sorted(node_ids, key=_sort_key):
        previous_tags = tuple(previous_source_map.get(node_id, ()))
        source_map[node_id] = previous_tags or (stage_id,)
    return source_map


def collect_endpoint_pool_mainnodes(
    *,
    base_dir: Path,
    source_specs: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[set[str], dict[str, tuple[str, ...]]]:
    source_map: dict[str, tuple[str, ...]] = {}
    for source_name, relative_paths in source_specs:
        for relative_path in relative_paths:
            path = base_dir / relative_path
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as fp:
                rows = list(csv.DictReader(fp))
            if not rows:
                break
            if "node_id" in rows[0]:
                for row in rows:
                    node_id = str(row.get("node_id") or "").strip()
                    if not node_id:
                        continue
                    raw_tags = str(row.get("source_tags") or "").strip()
                    if raw_tags:
                        tags = tuple(tag for tag in raw_tags.split(";") if tag)
                    else:
                        tags = (source_name,)
                    merged = set(source_map.get(node_id, ()))
                    merged.update(tags)
                    source_map[node_id] = tuple(sorted(merged, key=_sort_key))
            else:
                for row in rows:
                    for field in ("a_node_id", "b_node_id"):
                        node_id = str(row.get(field) or "").strip()
                        if not node_id:
                            continue
                        merged = set(source_map.get(node_id, ()))
                        merged.add(source_name)
                        source_map[node_id] = tuple(sorted(merged, key=_sort_key))
            break
    return set(source_map), source_map


def write_endpoint_pool_outputs(
    *,
    out_dir: Path,
    source_map: dict[str, tuple[str, ...]],
    stage_id: str,
    semantic_nodes: Optional[dict[str, SemanticNodeRecord]] = None,
    debug: bool = True,
) -> tuple[Path, Path, Optional[Path]]:
    rows = [
        {"node_id": node_id, "source_tags": ";".join(tags)}
        for node_id, tags in sorted(source_map.items(), key=lambda item: _sort_key(item[0]))
    ]
    csv_path = out_dir / ENDPOINT_POOL_CSV_NAME
    summary_path = out_dir / ENDPOINT_POOL_SUMMARY_NAME
    geojson_path: Optional[Path] = None

    write_csv(csv_path, rows, ["node_id", "source_tags"])
    write_json(
        summary_path,
        {
            "stage_id": stage_id,
            "endpoint_pool_count": len(rows),
            "endpoint_pool_node_ids": [row["node_id"] for row in rows],
        },
    )

    if debug and semantic_nodes is not None:
        features = []
        for node_id, tags in sorted(source_map.items(), key=lambda item: _sort_key(item[0])):
            node = semantic_nodes.get(node_id)
            if node is None:
                continue
            features.append(
                {
                    "properties": {
                        "node_id": node.semantic_node_id,
                        "representative_node_id": node.representative_node_id,
                        "source_tags": list(tags),
                        "kind_2": node.kind_2,
                        "grade_2": node.grade_2,
                        "closed_con": node.closed_con,
                    },
                    "geometry": node.geometry,
                }
            )
        geojson_path = out_dir / ENDPOINT_POOL_NODES_NAME
        write_vector(geojson_path, features)

    return csv_path, summary_path, geojson_path
