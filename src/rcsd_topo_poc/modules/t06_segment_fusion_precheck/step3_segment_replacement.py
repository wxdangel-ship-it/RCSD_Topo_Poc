from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .graph_builders import NodeCanonicalizer
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int, unique_preserve_order
from .schemas import (
    STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
    STEP3_ADDED_RCSD_NODES_STEM,
    STEP3_ADDED_RCSD_ROADS_STEM,
    STEP3_CHANGE_AUDIT_FIELDS,
    STEP3_DIR,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_ID_COLLISION_AUDIT_FIELDS,
    STEP3_ID_COLLISION_AUDIT_STEM,
    STEP3_JUNCTION_REBUILD_AUDIT_FIELDS,
    STEP3_JUNCTION_REBUILD_AUDIT_STEM,
    STEP3_REMOVED_SWSD_NODES_STEM,
    STEP3_REMOVED_SWSD_ROADS_STEM,
    STEP3_REPLACEMENT_UNIT_FIELDS,
    STEP3_REPLACEMENT_UNITS_STEM,
    STEP3_SUMMARY,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
    STEP3_UNREPLACED_RCSD_ROAD_FIELDS,
    STEP3_UNREPLACED_RCSD_ROADS_STEM,
    T06Step3Artifacts,
    feature,
)


INHERITED_NODE_FIELDS = ["kind", "grade", "kind_2", "grade_2", "closed_con"]


@dataclass
class ReplacementUnit:
    segment_id: str
    pair_nodes: list[str]
    junc_nodes: list[str]
    junc_kind2_exempt_nodes: list[str]
    swsd_road_ids: list[str]
    rcsd_road_ids: list[str]
    retained_node_ids: list[str]
    rcsd_pair_nodes: list[str]
    rcsd_junc_nodes: list[str]
    optional_allowed_rcsd_nodes: list[str]
    geometry: Any
    status: str = "passed"
    reason: str = "replaceable"
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    added_rcsd_node_ids: list[str] = field(default_factory=list)


@dataclass
class SpecialJunctionGroup:
    special_junction_id: str
    associated_segment_ids: list[str]
    rcsd_junction_node_ids: list[str]
    rcsd_junction_road_ids: list[str]


@dataclass
class JunctionState:
    c_id: str
    replacement_segment_ids: list[str] = field(default_factory=list)
    mapped_rcsd_semantic_ids: list[str] = field(default_factory=list)
    original_member_node_ids: list[str] = field(default_factory=list)
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    remaining_swsd_node_ids: list[str] = field(default_factory=list)
    added_rcsd_node_ids: list[str] = field(default_factory=list)
    original_main_props: dict[str, Any] = field(default_factory=dict)


def run_t06_step3_segment_replacement(
    *,
    step2_replaceable_path: str | Path,
    step2_special_junction_group_audit_path: str | Path | None = None,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    source_field_name: str = "source",
    rcsd_source_value: int = 1,
    swsd_source_value: int = 2,
    progress: bool = False,
) -> T06Step3Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP3_DIR)
    replaceable = read_features(step2_replaceable_path)
    swsd_segments = read_features(swsd_segment_path)
    swsd_roads = read_features(swsd_roads_path)
    swsd_nodes = read_features(swsd_nodes_path)
    rcsd_roads = read_features(rcsdroad_path)
    rcsd_nodes = read_features(rcsdnode_path)

    segment_by_id = _index_by_id(swsd_segments)
    swsd_road_by_id = _index_by_id(swsd_roads)
    swsd_node_by_id = _index_by_id(swsd_nodes)
    rcsd_road_by_id = _index_by_id(rcsd_roads)
    rcsd_node_by_id = _index_by_id(rcsd_nodes)
    canonicalizer = NodeCanonicalizer.from_node_features(rcsd_nodes)

    units = _build_replacement_units(replaceable, segment_by_id, progress=progress)
    passed_units = [unit for unit in units if unit.status == "passed"]
    passed_unit_ids = {unit.segment_id for unit in passed_units}
    special_group_audit_path = _resolve_special_junction_group_audit_path(
        step2_replaceable_path=step2_replaceable_path,
        explicit_path=step2_special_junction_group_audit_path,
    )
    special_groups = _read_passed_special_junction_groups(special_group_audit_path)
    special_added_road_to_segments = _special_group_entity_segments(
        groups=special_groups,
        entity_attr="rcsd_junction_road_ids",
        passed_unit_ids=passed_unit_ids,
    )
    special_added_node_to_segments = _special_group_entity_segments(
        groups=special_groups,
        entity_attr="rcsd_junction_node_ids",
        passed_unit_ids=passed_unit_ids,
    )

    removed_road_to_segments: dict[str, list[str]] = defaultdict(list)
    for unit in passed_units:
        for road_id in unit.swsd_road_ids:
            if road_id in swsd_road_by_id:
                removed_road_to_segments[road_id].append(unit.segment_id)

    removed_node_to_segments: dict[str, list[str]] = defaultdict(list)
    for road_id, segment_ids in removed_road_to_segments.items():
        for node_id in _road_endpoint_node_ids(swsd_road_by_id[road_id]):
            for segment_id in segment_ids:
                if segment_id not in removed_node_to_segments[node_id]:
                    removed_node_to_segments[node_id].append(segment_id)

    for unit in passed_units:
        unit.removed_swsd_node_ids = unique_preserve_order(
            [
                node_id
                for road_id in unit.swsd_road_ids
                if road_id in swsd_road_by_id
                for node_id in _road_endpoint_node_ids(swsd_road_by_id[road_id])
            ]
        )

    added_road_to_segments: dict[str, list[str]] = defaultdict(list)
    for unit in passed_units:
        for road_id in unit.rcsd_road_ids:
            if road_id in rcsd_road_by_id:
                added_road_to_segments[road_id].append(unit.segment_id)
    for road_id, segment_ids in special_added_road_to_segments.items():
        if road_id in rcsd_road_by_id:
            _append_unique_segments(added_road_to_segments[road_id], segment_ids)

    selected_rcsd_semantic_ids = _selected_rcsd_semantic_ids(passed_units)
    selected_rcsd_raw_node_ids = _selected_rcsd_raw_node_ids(added_road_to_segments, rcsd_road_by_id)
    selected_rcsd_raw_node_ids.update(node_id for node_id in special_added_node_to_segments if node_id in rcsd_node_by_id)
    for node_id in special_added_node_to_segments:
        node = rcsd_node_by_id.get(node_id)
        if node is None:
            continue
        selected_rcsd_semantic_ids.add(canonicalizer.canonicalize(node_id))
    added_node_to_segments = _select_added_rcsd_nodes(
        rcsd_nodes=rcsd_nodes,
        selected_raw_node_ids=selected_rcsd_raw_node_ids,
        selected_semantic_node_ids=selected_rcsd_semantic_ids,
        canonicalizer=canonicalizer,
        units=passed_units,
    )
    for node_id, segment_ids in special_added_node_to_segments.items():
        if node_id in rcsd_node_by_id:
            _append_unique_segments(added_node_to_segments.setdefault(node_id, []), segment_ids)
    for unit in passed_units:
        unit.added_rcsd_node_ids = unique_preserve_order(
            [
                node_id
                for node_id, segment_ids in added_node_to_segments.items()
                if unit.segment_id in segment_ids
            ]
        )

    junctions = _build_junction_states(
        units=passed_units,
        swsd_nodes=swsd_nodes,
        removed_node_ids=set(removed_node_to_segments),
        added_node_to_segments=added_node_to_segments,
        rcsd_nodes=rcsd_nodes,
        canonicalizer=canonicalizer,
    )

    frcsd_roads = _build_frcsd_roads(
        swsd_roads=swsd_roads,
        rcsd_roads=rcsd_roads,
        removed_road_ids=set(removed_road_to_segments),
        added_road_ids=set(added_road_to_segments),
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    frcsd_nodes = _build_frcsd_nodes(
        swsd_nodes=swsd_nodes,
        rcsd_nodes=rcsd_nodes,
        removed_node_ids=set(removed_node_to_segments),
        added_node_ids=set(added_node_to_segments),
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    junction_audit_rows = _apply_junction_rebuild(
        frcsd_nodes,
        junctions=junctions,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )

    replacement_unit_rows = [feature(_replacement_unit_row(unit), unit.geometry) for unit in units]
    removed_road_rows = _change_rows(removed_road_to_segments, "road", swsd_source_value, "replaced_swsd_segment")
    removed_node_rows = _change_rows(removed_node_to_segments, "node", swsd_source_value, "removed_swsd_road_endpoint")
    added_road_rows = _change_rows(added_road_to_segments, "road", rcsd_source_value, "retained_rcsd_segment_road")
    added_node_rows = _change_rows(added_node_to_segments, "node", rcsd_source_value, "retained_rcsd_segment_node")
    unreplaced_rcsd_road_rows = _unreplaced_rcsd_road_rows(
        rcsd_roads=rcsd_roads,
        added_road_ids=set(added_road_to_segments),
        source_value=rcsd_source_value,
    )
    collision_rows = _id_collision_rows(
        retained_swsd_road_ids=_feature_id_set(frcsd_roads, source_field_name, swsd_source_value),
        retained_swsd_node_ids=_feature_id_set(frcsd_nodes, source_field_name, swsd_source_value),
        added_rcsd_road_ids=set(added_road_to_segments),
        added_rcsd_node_ids=set(added_node_to_segments),
    )
    segment_relation_rows = _build_swsd_frcsd_segment_relation_rows(
        swsd_segments=swsd_segments,
        units=units,
        frcsd_roads=frcsd_roads,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )

    road_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_ROAD_STEM,
        features=frcsd_roads,
        fieldnames=_fieldnames(frcsd_roads, ["id", source_field_name]),
    )
    node_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        features=frcsd_nodes,
        fieldnames=_fieldnames(frcsd_nodes, ["id", "mainnodeid", source_field_name]),
    )
    replacement_unit_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_REPLACEMENT_UNITS_STEM,
        features=replacement_unit_rows,
        fieldnames=STEP3_REPLACEMENT_UNIT_FIELDS,
    )
    segment_relation_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
        features=segment_relation_rows,
        fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    )
    junction_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_JUNCTION_REBUILD_AUDIT_STEM,
        features=junction_audit_rows,
        fieldnames=STEP3_JUNCTION_REBUILD_AUDIT_FIELDS,
    )
    removed_road_paths = write_feature_triplet(step_root=step_root, stem=STEP3_REMOVED_SWSD_ROADS_STEM, features=removed_road_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    removed_node_paths = write_feature_triplet(step_root=step_root, stem=STEP3_REMOVED_SWSD_NODES_STEM, features=removed_node_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    added_road_paths = write_feature_triplet(step_root=step_root, stem=STEP3_ADDED_RCSD_ROADS_STEM, features=added_road_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    added_node_paths = write_feature_triplet(step_root=step_root, stem=STEP3_ADDED_RCSD_NODES_STEM, features=added_node_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    unreplaced_rcsd_road_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_UNREPLACED_RCSD_ROADS_STEM,
        features=unreplaced_rcsd_road_rows,
        fieldnames=STEP3_UNREPLACED_RCSD_ROAD_FIELDS,
    )
    collision_paths = write_feature_triplet(step_root=step_root, stem=STEP3_ID_COLLISION_AUDIT_STEM, features=collision_rows, fieldnames=STEP3_ID_COLLISION_AUDIT_FIELDS)

    summary_path = step_root / STEP3_SUMMARY
    write_json(
        summary_path,
        {
            "run_id": resolved_run_id,
            "input_paths": {
                "step2_replaceable_path": str(step2_replaceable_path),
                "step2_special_junction_group_audit_path": str(special_group_audit_path) if special_group_audit_path is not None else None,
                "swsd_segment_path": str(swsd_segment_path),
                "swsd_roads_path": str(swsd_roads_path),
                "swsd_nodes_path": str(swsd_nodes_path),
                "rcsdroad_path": str(rcsdroad_path),
                "rcsdnode_path": str(rcsdnode_path),
            },
            "params": {
                "source_field_name": source_field_name,
                "rcsd_source_value": rcsd_source_value,
                "swsd_source_value": swsd_source_value,
                "id_collision_policy": "keep_original_ids_and_audit_with_source_field",
                "new_mainnode_selection_priority": ["original_mainnode_if_retained", "remaining_swsd_node_min_id", "added_rcsd_node_min_id"],
            },
            "input_replaceable_count": len(replaceable),
            "replacement_unit_count": len(units),
            "replacement_unit_success_count": len(passed_units),
            "replacement_unit_failure_count": len(units) - len(passed_units),
            "removed_swsd_road_count": len(removed_road_to_segments),
            "removed_swsd_node_count": len(removed_node_to_segments),
            "added_rcsd_road_count": len(added_road_to_segments),
            "added_rcsd_node_count": len(added_node_to_segments),
            "special_junction_group_consumed_count": len(special_groups),
            "special_junction_added_rcsd_road_count": len(
                {road_id for road_id in special_added_road_to_segments if road_id in rcsd_road_by_id}
            ),
            "special_junction_added_rcsd_node_count": len(
                {node_id for node_id in special_added_node_to_segments if node_id in rcsd_node_by_id}
            ),
            "unreplaced_rcsd_road_count": len(unreplaced_rcsd_road_rows),
            "unreplaced_rcsd_road_length_m": _round_length(sum(_feature_length(row) for row in unreplaced_rcsd_road_rows)),
            "junction_c_count": len(junctions),
            "junction_rebuilt_count": sum(1 for row in junction_audit_rows if row["properties"].get("new_mainnode_id")),
            "mainnode_reselected_count": sum(1 for row in junction_audit_rows if row["properties"].get("original_mainnode_removed")),
            "road_id_collision_count": sum(1 for row in collision_rows if row["properties"].get("entity_type") == "road"),
            "node_id_collision_count": sum(1 for row in collision_rows if row["properties"].get("entity_type") == "node"),
            "frcsd_road_count": len(frcsd_roads),
            "frcsd_node_count": len(frcsd_nodes),
            "segment_relation_count": len(segment_relation_rows),
            "segment_relation_replaced_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "replaced"),
            "segment_relation_retained_swsd_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "retained_swsd"),
            "segment_relation_failed_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "failed"),
            "outputs": {
                **{f"frcsd_road_{key}": str(value) for key, value in road_paths.items()},
                **{f"frcsd_node_{key}": str(value) for key, value in node_paths.items()},
                **{f"replacement_units_{key}": str(value) for key, value in replacement_unit_paths.items()},
                **{f"swsd_frcsd_segment_relation_{key}": str(value) for key, value in segment_relation_paths.items()},
                **{f"junction_rebuild_audit_{key}": str(value) for key, value in junction_paths.items()},
                **{f"removed_swsd_roads_{key}": str(value) for key, value in removed_road_paths.items()},
                **{f"removed_swsd_nodes_{key}": str(value) for key, value in removed_node_paths.items()},
                **{f"added_rcsd_roads_{key}": str(value) for key, value in added_road_paths.items()},
                **{f"added_rcsd_nodes_{key}": str(value) for key, value in added_node_paths.items()},
                **{f"unreplaced_rcsd_roads_{key}": str(value) for key, value in unreplaced_rcsd_road_paths.items()},
                **{f"id_collision_audit_{key}": str(value) for key, value in collision_paths.items()},
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "SWSD removals and RCSD additions are explicit copy-on-write sets; passed special junction groups add RCSD internal entities as group-level replacements; junction C rebuild is audited",
                "geometry_semantics": "Step3 does not infer geometry; it consumes Step2 retained RCSDSegment features and passed special junction group audit entities",
                "audit_traceability": "replacement units, special junction group consumption, removed/added entities, id collisions and junction rebuild records are written",
                "segment_relation_traceability": "each SWSD Segment relation records F-RCSD carrier road ids, source values and node mapping evidence",
                "performance_verifiable": "input, replacement, output and audit counts are recorded in summary",
            },
        },
    )

    return T06Step3Artifacts(
        run_id=resolved_run_id,
        run_root=run_root,
        step_root=step_root,
        frcsd_road_gpkg_path=road_paths["gpkg"],
        frcsd_node_gpkg_path=node_paths["gpkg"],
        replacement_units_gpkg_path=replacement_unit_paths["gpkg"],
        swsd_frcsd_segment_relation_gpkg_path=segment_relation_paths["gpkg"],
        junction_rebuild_audit_gpkg_path=junction_paths["gpkg"],
        summary_path=summary_path,
    )


def _resolve_special_junction_group_audit_path(
    *,
    step2_replaceable_path: str | Path,
    explicit_path: str | Path | None,
) -> Path | None:
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"special junction group audit file does not exist: {path}")
        return path
    step2_dir = Path(step2_replaceable_path).parent
    for suffix in (".json", ".geojson", ".gpkg"):
        path = step2_dir / f"{STEP2_SPECIAL_JUNCTION_GROUPS_STEM}{suffix}"
        if path.is_file():
            return path
    return None


def _read_passed_special_junction_groups(path: Path | None) -> list[SpecialJunctionGroup]:
    if path is None:
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", []) if isinstance(payload, dict) else []
        rows = [{"properties": dict(item.get("properties") or {})} for item in features]
    else:
        rows = read_features(path)
    groups: list[SpecialJunctionGroup] = []
    for item in rows:
        props = dict(item.get("properties") or {})
        if str(props.get("gate_status") or "") != "passed":
            continue
        associated_segment_ids = _parse_list(props.get("associated_segment_ids"))
        if not associated_segment_ids:
            continue
        groups.append(
            SpecialJunctionGroup(
                special_junction_id=_safe_normalize(props.get("special_junction_id") or ""),
                associated_segment_ids=associated_segment_ids,
                rcsd_junction_node_ids=_parse_list(props.get("rcsd_junction_node_ids")),
                rcsd_junction_road_ids=_parse_list(props.get("rcsd_junction_road_ids")),
            )
        )
    return groups


def _special_group_entity_segments(
    *,
    groups: list[SpecialJunctionGroup],
    entity_attr: str,
    passed_unit_ids: set[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for group in groups:
        segment_ids = [segment_id for segment_id in group.associated_segment_ids if segment_id in passed_unit_ids]
        if not segment_ids:
            continue
        for entity_id in getattr(group, entity_attr):
            _append_unique_segments(result[entity_id], segment_ids)
    return dict(result)


def _append_unique_segments(target: list[str], segment_ids: list[str]) -> None:
    for segment_id in segment_ids:
        if segment_id not in target:
            target.append(segment_id)


def _build_replacement_units(replaceable: list[dict[str, Any]], segment_by_id: dict[str, dict[str, Any]], *, progress: bool) -> list[ReplacementUnit]:
    units: list[ReplacementUnit] = []
    for index, item in enumerate(replaceable, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step3] parsed {index}/{len(replaceable)} replaceable rows", flush=True)
        props = dict(item.get("properties") or {})
        segment_id = _safe_normalize(props.get("swsd_segment_id") or props.get("id") or f"segment_{index}")
        segment = segment_by_id.get(segment_id)
        segment_props = dict(segment.get("properties") or {}) if segment is not None else {}
        pair_nodes = _parse_list(props.get("swsd_pair_nodes", segment_props.get("pair_nodes")))
        junc_nodes = _parse_list(props.get("swsd_junc_nodes", segment_props.get("junc_nodes")))
        swsd_road_ids = _parse_list(segment_props.get("roads"))
        rcsd_road_ids = _parse_list(props.get("rcsd_road_ids") or props.get("retained_rcsd_road_ids"))
        retained_node_ids = _parse_list(props.get("retained_node_ids"))
        unit = ReplacementUnit(
            segment_id=segment_id,
            pair_nodes=pair_nodes,
            junc_nodes=junc_nodes,
            junc_kind2_exempt_nodes=_parse_list(props.get("junc_kind2_exempt_nodes")),
            swsd_road_ids=swsd_road_ids,
            rcsd_road_ids=rcsd_road_ids,
            retained_node_ids=retained_node_ids,
            rcsd_pair_nodes=_parse_list(props.get("rcsd_pair_nodes")),
            rcsd_junc_nodes=_parse_list(props.get("rcsd_junc_nodes")),
            optional_allowed_rcsd_nodes=_parse_list(props.get("optional_allowed_rcsd_nodes")),
            geometry=item.get("geometry") or (segment or {}).get("geometry"),
        )
        if segment is None:
            unit.status = "failed"
            unit.reason = "missing_swsd_segment"
        elif not swsd_road_ids:
            unit.status = "failed"
            unit.reason = "missing_swsd_segment_roads"
        elif not rcsd_road_ids:
            unit.status = "failed"
            unit.reason = "missing_rcsd_road_ids"
        units.append(unit)
    return units


def _build_junction_states(
    *,
    units: list[ReplacementUnit],
    swsd_nodes: list[dict[str, Any]],
    removed_node_ids: set[str],
    added_node_to_segments: dict[str, list[str]],
    rcsd_nodes: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, JunctionState]:
    junctions: dict[str, JunctionState] = {}
    for unit in units:
        c_ids = unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes])
        mapped_by_c = _mapped_rcsd_semantic_by_c(unit)
        for c_id in c_ids:
            state = junctions.setdefault(c_id, JunctionState(c_id=c_id))
            if unit.segment_id not in state.replacement_segment_ids:
                state.replacement_segment_ids.append(unit.segment_id)
            state.mapped_rcsd_semantic_ids = unique_preserve_order(
                [
                    *state.mapped_rcsd_semantic_ids,
                    *[canonicalizer.canonicalize(node_id) for node_id in mapped_by_c.get(c_id, [])],
                ]
            )

    swsd_group_members = _swsd_group_members(swsd_nodes, set(junctions))
    for c_id, state in junctions.items():
        group = swsd_group_members.get(c_id, [])
        state.original_member_node_ids = [_feature_id(item) for item in group]
        state.removed_swsd_node_ids = [node_id for node_id in state.original_member_node_ids if node_id in removed_node_ids]
        state.remaining_swsd_node_ids = [node_id for node_id in state.original_member_node_ids if node_id not in removed_node_ids]
        state.original_main_props = _original_main_props(c_id, group)

    added_node_ids = set(added_node_to_segments)
    for node in rcsd_nodes:
        node_id = _feature_id(node)
        if node_id not in added_node_ids:
            continue
        canonical_id = canonicalizer.canonicalize(node_id)
        segment_ids = set(added_node_to_segments[node_id])
        for state in junctions.values():
            if canonical_id in state.mapped_rcsd_semantic_ids and segment_ids.intersection(state.replacement_segment_ids):
                state.added_rcsd_node_ids.append(node_id)
    for state in junctions.values():
        state.added_rcsd_node_ids = unique_preserve_order(state.added_rcsd_node_ids)
    return junctions


def _apply_junction_rebuild(
    frcsd_nodes: list[dict[str, Any]],
    *,
    junctions: dict[str, JunctionState],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    node_by_key = {(_source_key(item, source_field_name), _feature_id(item)): item for item in frcsd_nodes}
    rows: list[dict[str, Any]] = []
    for state in junctions.values():
        member_keys = [
            (str(swsd_source_value), node_id)
            for node_id in state.remaining_swsd_node_ids
            if (str(swsd_source_value), node_id) in node_by_key
        ] + [
            (str(rcsd_source_value), node_id)
            for node_id in state.added_rcsd_node_ids
            if (str(rcsd_source_value), node_id) in node_by_key
        ]
        original_main_key = (str(swsd_source_value), state.c_id)
        original_main_removed = state.c_id in state.removed_swsd_node_ids or original_main_key not in member_keys
        new_main_id, reason = _choose_new_mainnode_id(state, member_keys, original_main_key)
        inherited = {field: state.original_main_props.get(field) for field in INHERITED_NODE_FIELDS}
        if new_main_id is not None:
            for key in member_keys:
                props = node_by_key[key]["properties"]
                props["mainnodeid"] = new_main_id
                for field, value in inherited.items():
                    props[field] = value
        rows.append(
            feature(
                {
                    "junction_c_id": state.c_id,
                    "replacement_segment_ids": state.replacement_segment_ids,
                    "original_mainnode_id": state.c_id,
                    "original_mainnode_removed": original_main_removed,
                    "new_mainnode_id": new_main_id,
                    "mainnode_selection_reason": reason,
                    "original_member_node_ids": state.original_member_node_ids,
                    "removed_swsd_node_ids": state.removed_swsd_node_ids,
                    "remaining_swsd_node_ids": state.remaining_swsd_node_ids,
                    "added_rcsd_node_ids": state.added_rcsd_node_ids,
                    "rebuilt_node_ids": [key[1] for key in member_keys],
                    "inherited_kind": inherited.get("kind"),
                    "inherited_grade": inherited.get("grade"),
                    "inherited_kind_2": inherited.get("kind_2"),
                    "inherited_grade_2": inherited.get("grade_2"),
                    "inherited_closed_con": inherited.get("closed_con"),
                },
                None,
            )
        )
    return rows


def _choose_new_mainnode_id(state: JunctionState, member_keys: list[tuple[str, str]], original_main_key: tuple[str, str]) -> tuple[str | None, str]:
    if original_main_key in member_keys:
        return state.c_id, "original_mainnode_retained"
    remaining = sorted(state.remaining_swsd_node_ids, key=_id_sort_key)
    for node_id in remaining:
        if any(key[1] == node_id for key in member_keys):
            return node_id, "remaining_swsd_node_min_id"
    added = sorted(state.added_rcsd_node_ids, key=_id_sort_key)
    for node_id in added:
        if any(key[1] == node_id for key in member_keys):
            return node_id, "added_rcsd_node_min_id"
    return None, "no_nodes_to_rebuild"


def _build_frcsd_roads(
    *,
    swsd_roads: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    removed_road_ids: set[str],
    added_road_ids: set[str],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for road in swsd_roads:
        if _feature_id(road) not in removed_road_ids:
            rows.append(_with_source(road, source_field_name, swsd_source_value))
    for road in rcsd_roads:
        if _feature_id(road) in added_road_ids:
            rows.append(_with_source(road, source_field_name, rcsd_source_value))
    return rows


def _build_frcsd_nodes(
    *,
    swsd_nodes: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    removed_node_ids: set[str],
    added_node_ids: set[str],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in swsd_nodes:
        if _feature_id(node) not in removed_node_ids:
            rows.append(_with_source(node, source_field_name, swsd_source_value))
    for node in rcsd_nodes:
        if _feature_id(node) in added_node_ids:
            rows.append(_with_source(node, source_field_name, rcsd_source_value))
    return rows


def _build_swsd_frcsd_segment_relation_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    units: list[ReplacementUnit],
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    unit_by_segment = {unit.segment_id: unit for unit in units}
    frcsd_road_by_source_id = {(_source_key(road, source_field_name), _feature_id(road)): road for road in frcsd_roads}
    retained_by_segment = _retained_swsd_roads_by_segment(
        frcsd_roads=frcsd_roads,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
    )
    rows: list[dict[str, Any]] = []
    for segment in swsd_segments:
        segment_id = _feature_id(segment)
        props = dict(segment.get("properties") or {})
        pair_nodes = _parse_list(props.get("pair_nodes"))
        junc_nodes = _parse_list(props.get("junc_nodes"))
        swsd_road_ids = _parse_list(props.get("roads"))
        unit = unit_by_segment.get(segment_id)
        if unit is not None:
            pair_nodes = unit.pair_nodes or pair_nodes
            junc_nodes = unit.junc_nodes or junc_nodes
        relation_status = "failed"
        relation_reason = "missing_frcsd_carrier_roads"
        removed_swsd_road_ids: list[str] = []
        frcsd_road_ids: list[str] = []
        frcsd_road_source_values: list[int] = []
        rcsd_pair_nodes: list[str] = []
        rcsd_junc_nodes: list[str] = []
        node_map: list[dict[str, Any]] = []
        risk_flags: list[str] = []

        if unit is not None and unit.status == "passed":
            removed_swsd_road_ids = unit.swsd_road_ids
            rcsd_pair_nodes = unit.rcsd_pair_nodes
            rcsd_junc_nodes = unit.rcsd_junc_nodes
            present_rcsd_road_ids = [
                road_id
                for road_id in unit.rcsd_road_ids
                if (str(rcsd_source_value), road_id) in frcsd_road_by_source_id
            ]
            missing_rcsd_road_ids = [road_id for road_id in unit.rcsd_road_ids if road_id not in present_rcsd_road_ids]
            frcsd_road_ids = present_rcsd_road_ids
            frcsd_road_source_values = [rcsd_source_value] if present_rcsd_road_ids else []
            relation_status = "replaced" if present_rcsd_road_ids else "failed"
            relation_reason = "replacement_unit_passed" if present_rcsd_road_ids else "replacement_roads_missing_in_frcsd"
            if missing_rcsd_road_ids:
                risk_flags.append("missing_replacement_frcsd_roads")
            node_map = _segment_node_map(
                swsd_pair_nodes=unit.pair_nodes,
                swsd_junc_nodes=unit.junc_nodes,
                junc_kind2_exempt_nodes=unit.junc_kind2_exempt_nodes,
                mapped_by_swsd_node=_mapped_rcsd_semantic_by_c(unit),
                identity=False,
            )
        elif unit is not None:
            relation_reason = unit.reason
            risk_flags.append("replacement_unit_failed")
            node_map = _segment_node_map(
                swsd_pair_nodes=pair_nodes,
                swsd_junc_nodes=junc_nodes,
                junc_kind2_exempt_nodes=unit.junc_kind2_exempt_nodes,
                mapped_by_swsd_node={},
                identity=False,
            )
        else:
            retained_ids = _retained_swsd_road_ids_for_segment(
                segment_id=segment_id,
                swsd_road_ids=swsd_road_ids,
                retained_by_segment=retained_by_segment,
                frcsd_road_by_source_id=frcsd_road_by_source_id,
                swsd_source_value=swsd_source_value,
            )
            frcsd_road_ids = retained_ids
            frcsd_road_source_values = [swsd_source_value] if retained_ids else []
            relation_status = "retained_swsd" if retained_ids else "failed"
            relation_reason = "retained_swsd_segment" if retained_ids else "retained_swsd_roads_missing_in_frcsd"
            if not retained_ids:
                risk_flags.append("missing_retained_swsd_frcsd_roads")
            node_map = _segment_node_map(
                swsd_pair_nodes=pair_nodes,
                swsd_junc_nodes=junc_nodes,
                junc_kind2_exempt_nodes=_parse_list(props.get("junc_kind2_exempt_nodes")),
                mapped_by_swsd_node={},
                identity=True,
            )

        source_values = unique_preserve_order([str(value) for value in frcsd_road_source_values])
        rows.append(
            feature(
                {
                    "swsd_segment_id": segment_id,
                    "relation_status": relation_status,
                    "relation_reason": relation_reason,
                    "swsd_pair_nodes": pair_nodes,
                    "swsd_junc_nodes": junc_nodes,
                    "junc_kind2_exempt_nodes": (unit.junc_kind2_exempt_nodes if unit is not None else _parse_list(props.get("junc_kind2_exempt_nodes"))),
                    "swsd_road_ids": swsd_road_ids,
                    "removed_swsd_road_ids": removed_swsd_road_ids,
                    "frcsd_road_ids": frcsd_road_ids,
                    "frcsd_road_source_values": frcsd_road_source_values,
                    "rcsd_pair_nodes": rcsd_pair_nodes,
                    "rcsd_junc_nodes": rcsd_junc_nodes,
                    "junction_c_ids": unique_preserve_order([*pair_nodes, *junc_nodes]),
                    "swsd_to_frcsd_node_map": node_map,
                    "source_mix": "+".join(f"source_{value}" for value in source_values),
                    "risk_flags": risk_flags,
                },
                segment.get("geometry"),
            )
        )
    return rows


def _retained_swsd_roads_by_segment(
    *,
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in frcsd_roads:
        if _source_key(road, source_field_name) != str(swsd_source_value):
            continue
        props = dict(road.get("properties") or {})
        road_id = _feature_id(road)
        for segment_id in _parse_list(props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id")):
            result[segment_id].append(road_id)
    return {segment_id: unique_preserve_order(road_ids) for segment_id, road_ids in result.items()}


def _retained_swsd_road_ids_for_segment(
    *,
    segment_id: str,
    swsd_road_ids: list[str],
    retained_by_segment: dict[str, list[str]],
    frcsd_road_by_source_id: dict[tuple[str, str], dict[str, Any]],
    swsd_source_value: int,
) -> list[str]:
    retained_ids = list(retained_by_segment.get(segment_id, []))
    for road_id in swsd_road_ids:
        if (str(swsd_source_value), road_id) in frcsd_road_by_source_id and road_id not in retained_ids:
            retained_ids.append(road_id)
    return retained_ids


def _segment_node_map(
    *,
    swsd_pair_nodes: list[str],
    swsd_junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    mapped_by_swsd_node: dict[str, list[str]],
    identity: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    exempt_nodes = set(junc_kind2_exempt_nodes)
    node_roles = [(node_id, "pair_node") for node_id in swsd_pair_nodes] + [
        (node_id, "junc_kind2_exempt_node" if node_id in exempt_nodes else "junc_node")
        for node_id in swsd_junc_nodes
    ]
    for swsd_node_id, node_role in node_roles:
        frcsd_node_ids = [swsd_node_id] if identity else mapped_by_swsd_node.get(swsd_node_id, [])
        rows.append(
            {
                "swsd_node_id": swsd_node_id,
                "frcsd_node_ids": frcsd_node_ids,
                "node_role": node_role,
                "mapping_status": "identity" if identity else ("mapped" if frcsd_node_ids else "missing"),
            }
        )
    return rows


def _mapped_rcsd_semantic_by_c(unit: ReplacementUnit) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for swsd_node, rcsd_node in zip(unit.pair_nodes, unit.rcsd_pair_nodes):
        result[swsd_node].append(rcsd_node)
    exempt = set(unit.junc_kind2_exempt_nodes)
    relation_junc_nodes = [node_id for node_id in unit.junc_nodes if node_id not in exempt]
    for swsd_node, rcsd_node in zip(relation_junc_nodes, unit.rcsd_junc_nodes):
        result[swsd_node].append(rcsd_node)
    exempt_junc_nodes = [node_id for node_id in unit.junc_nodes if node_id in exempt]
    if len(exempt_junc_nodes) == len(unit.optional_allowed_rcsd_nodes):
        for swsd_node, rcsd_node in zip(exempt_junc_nodes, unit.optional_allowed_rcsd_nodes):
            result[swsd_node].append(rcsd_node)
    return {key: unique_preserve_order(value) for key, value in result.items()}


def _selected_rcsd_semantic_ids(units: list[ReplacementUnit]) -> set[str]:
    selected: set[str] = set()
    for unit in units:
        selected.update(unit.retained_node_ids)
        selected.update(unit.rcsd_pair_nodes)
        selected.update(unit.rcsd_junc_nodes)
        selected.update(unit.optional_allowed_rcsd_nodes)
    return selected


def _selected_rcsd_raw_node_ids(added_road_to_segments: dict[str, list[str]], rcsd_road_by_id: dict[str, dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for road_id in added_road_to_segments:
        road = rcsd_road_by_id.get(road_id)
        if road is not None:
            result.update(_road_endpoint_node_ids(road))
    return result


def _select_added_rcsd_nodes(
    *,
    rcsd_nodes: list[dict[str, Any]],
    selected_raw_node_ids: set[str],
    selected_semantic_node_ids: set[str],
    canonicalizer: NodeCanonicalizer,
    units: list[ReplacementUnit],
) -> dict[str, list[str]]:
    semantic_to_segments: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        for semantic_id in unique_preserve_order([*unit.retained_node_ids, *unit.rcsd_pair_nodes, *unit.rcsd_junc_nodes, *unit.optional_allowed_rcsd_nodes]):
            semantic_to_segments[semantic_id].append(unit.segment_id)
    result: dict[str, list[str]] = {}
    for node in rcsd_nodes:
        node_id = _feature_id(node)
        canonical_id = canonicalizer.canonicalize(node_id)
        if node_id not in selected_raw_node_ids and canonical_id not in selected_semantic_node_ids:
            continue
        segment_ids = semantic_to_segments.get(canonical_id, [])
        if not segment_ids:
            segment_ids = [unit.segment_id for unit in units if node_id in unit.retained_node_ids]
        result[node_id] = unique_preserve_order(segment_ids)
    return result


def _swsd_group_members(swsd_nodes: list[dict[str, Any]], c_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in swsd_nodes:
        props = dict(node.get("properties") or {})
        node_id = _feature_id(node)
        semantic_ids = {node_id}
        mainnodeid = parse_positive_int(props.get("mainnodeid"))
        if mainnodeid is not None:
            semantic_ids.add(str(mainnodeid))
        for c_id in semantic_ids.intersection(c_ids):
            groups[c_id].append(node)
    return groups


def _original_main_props(c_id: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    for node in group:
        if _feature_id(node) == c_id:
            return dict(node.get("properties") or {})
    return dict((group[0].get("properties") or {}) if group else {})


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return unique_preserve_order(result)


def _index_by_id(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        try:
            result.setdefault(_feature_id(item), item)
        except ParseError:
            continue
    return result


def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))


def _safe_normalize(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return str(value)


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _with_source(item: dict[str, Any], source_field_name: str, source_value: int) -> dict[str, Any]:
    props = dict(item.get("properties") or {})
    props[source_field_name] = source_value
    return feature(props, item.get("geometry"))


def _source_key(item: dict[str, Any], source_field_name: str) -> str:
    return str((item.get("properties") or {}).get(source_field_name))


def _replacement_unit_row(unit: ReplacementUnit) -> dict[str, Any]:
    return {
        "swsd_segment_id": unit.segment_id,
        "unit_status": unit.status,
        "unit_reason": unit.reason,
        "swsd_pair_nodes": unit.pair_nodes,
        "swsd_junc_nodes": unit.junc_nodes,
        "junc_kind2_exempt_nodes": unit.junc_kind2_exempt_nodes,
        "swsd_road_ids": unit.swsd_road_ids,
        "removed_swsd_road_ids": unit.swsd_road_ids if unit.status == "passed" else [],
        "removed_swsd_node_ids": unit.removed_swsd_node_ids,
        "rcsd_road_ids": unit.rcsd_road_ids,
        "rcsd_node_ids": unit.added_rcsd_node_ids,
        "rcsd_pair_nodes": unit.rcsd_pair_nodes,
        "rcsd_junc_nodes": unit.rcsd_junc_nodes,
        "junction_c_ids": unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes]),
    }


def _change_rows(items: dict[str, list[str]], entity_type: str, source_value: int, reason: str) -> list[dict[str, Any]]:
    return [
        feature(
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "source": source_value,
                "reason": reason,
                "swsd_segment_ids": segment_ids,
            },
            None,
        )
        for entity_id, segment_ids in sorted(items.items(), key=lambda item: _id_sort_key(item[0]))
    ]


def _unreplaced_rcsd_road_rows(
    *,
    rcsd_roads: list[dict[str, Any]],
    added_road_ids: set[str],
    source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for road in rcsd_roads:
        try:
            road_id = _feature_id(road)
        except ParseError:
            continue
        if road_id in added_road_ids:
            continue
        props = dict(road.get("properties") or {})
        props.update(
            {
                "id": road_id,
                "replacement_status": "not_replaced",
                "audit_reason": "not_referenced_by_step2_replaceable_rcsd_segment",
                "source": source_value,
                "length_m": _round_length(_feature_length(road)),
            }
        )
        rows.append(feature(props, road.get("geometry")))
    return sorted(rows, key=lambda item: _id_sort_key(_feature_id(item)))


def _feature_id_set(features: list[dict[str, Any]], source_field_name: str, source_value: int) -> set[str]:
    return {
        _feature_id(item)
        for item in features
        if (item.get("properties") or {}).get(source_field_name) == source_value
    }


def _id_collision_rows(
    *,
    retained_swsd_road_ids: set[str],
    retained_swsd_node_ids: set[str],
    added_rcsd_road_ids: set[str],
    added_rcsd_node_ids: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity_type, swsd_ids, rcsd_ids in (
        ("road", retained_swsd_road_ids, added_rcsd_road_ids),
        ("node", retained_swsd_node_ids, added_rcsd_node_ids),
    ):
        for entity_id in sorted(swsd_ids.intersection(rcsd_ids), key=_id_sort_key):
            rows.append(
                feature(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "swsd_present": True,
                        "rcsd_present": True,
                        "policy": "keep_original_ids_and_audit_with_source_field",
                    },
                    None,
                )
            )
    return rows


def _fieldnames(features: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    fields: list[str] = []
    for field_name in preferred:
        if field_name not in fields:
            fields.append(field_name)
    for item in features:
        for field_name in (item.get("properties") or {}).keys():
            if field_name not in fields:
                fields.append(field_name)
    return fields


def _feature_length(feature_item: dict[str, Any]) -> float:
    geometry = feature_item.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)


def _id_sort_key(value: str) -> tuple[int, int | str]:
    parsed = parse_positive_int(value)
    if parsed is not None:
        return (0, parsed)
    return (1, value)
