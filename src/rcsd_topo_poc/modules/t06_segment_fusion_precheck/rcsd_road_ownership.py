from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from hashlib import sha1
import json
from numbers import Integral
from pathlib import Path
from typing import Any

from shapely.strtree import STRtree

from .graph_builders import NodeCanonicalizer
from .io import read_features, write_feature_triplet, write_json
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import (
    STEP3_CHANGE_AUDIT_FIELDS,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
    feature,
)


RCSD_ROAD_OWNERSHIP_STEM = "t06_rcsd_road_ownership"
MULTI_SEGMENT_CONNECTIVITY_GROUP_STEM = "t06_multi_segment_connectivity_group"
ADVANCE_RIGHT_FORMWAY_MASK = 128
OWNERSHIP_MATCH_BUFFER_M = 50.0
OWNERSHIP_TIGHT_BUFFER_M = 20.0

RCSD_ROAD_OWNERSHIP_FIELDS = [
    "rcsd_road_id",
    "owner_type",
    "owner_key",
    "owner_segment_id",
    "owner_segment_type",
    "connectivity_group_id",
    "special_junction_ids",
    "related_segment_ids",
    "candidate_segment_ids",
    "ownership_status",
    "ownership_confidence",
    "ownership_evidence_types",
    "ownership_reason",
    "replacement_status",
    "replacement_action",
    "final_road_ids",
    "risk_flags",
    "count_in_rcsd_road_metric",
    "count_in_segment_metric",
]

MULTI_SEGMENT_CONNECTIVITY_GROUP_FIELDS = [
    "connectivity_group_id",
    "connectivity_kind",
    "rcsd_road_ids",
    "final_road_ids",
    "terminal_node_ids",
    "related_segment_ids",
    "terminal_attachment_evidence",
    "connectivity_status",
    "replacement_status",
    "blocked_reason",
    "risk_flags",
    "count_in_rcsd_road_metric",
    "count_in_segment_metric",
]


@dataclass(frozen=True)
class OwnershipOutputs:
    ownership_rows: list[dict[str, Any]]
    connectivity_group_rows: list[dict[str, Any]]
    ownership_paths: dict[str, Any]
    connectivity_group_paths: dict[str, Any]
    summary: dict[str, Any]


class _SegmentSpatialIndex:
    def __init__(self, segments: list[dict[str, Any]]) -> None:
        self.segment_by_id: dict[str, dict[str, Any]] = {}
        self.segment_type_by_id: dict[str, str] = {}
        self.geometries: list[Any] = []
        self.segment_ids: list[str] = []
        self.geometry_index_by_identity: dict[int, int] = {}
        for segment in segments:
            segment_id = _feature_id(segment)
            geometry = segment.get("geometry")
            if not segment_id or not _usable_geometry(geometry):
                continue
            props = segment.get("properties") or {}
            self.segment_by_id[segment_id] = segment
            self.segment_type_by_id[segment_id] = str(props.get("segment_type") or "normal")
            self.geometry_index_by_identity[id(geometry)] = len(self.geometries)
            self.geometries.append(geometry)
            self.segment_ids.append(segment_id)
        self.tree = STRtree(self.geometries) if self.geometries else None

    def scored_candidates(
        self,
        road_geometry: Any,
        *,
        segment_type: str | None = None,
    ) -> list[tuple[str, float, float, float]]:
        if self.tree is None or not _usable_geometry(road_geometry):
            return []
        road_length = float(road_geometry.length or 0.0)
        if road_length <= 0.0:
            return []
        query_result = self.tree.query(road_geometry.buffer(OWNERSHIP_MATCH_BUFFER_M))
        indexes: list[int] = []
        for value in query_result:
            if isinstance(value, Integral):
                indexes.append(int(value))
            else:
                index = self.geometry_index_by_identity.get(id(value))
                if index is not None:
                    indexes.append(index)
        scored: list[tuple[str, float, float, float]] = []
        for index in indexes:
            segment_id = self.segment_ids[index]
            if segment_type is not None and self.segment_type_by_id[segment_id] != segment_type:
                continue
            segment_geometry = self.geometries[index]
            distance = float(road_geometry.distance(segment_geometry))
            if distance > OWNERSHIP_MATCH_BUFFER_M:
                continue
            cover20 = _coverage_ratio(road_geometry, segment_geometry, OWNERSHIP_TIGHT_BUFFER_M)
            cover50 = _coverage_ratio(road_geometry, segment_geometry, OWNERSHIP_MATCH_BUFFER_M)
            scored.append((segment_id, cover20, cover50, distance))
        return sorted(scored, key=lambda item: (-item[1], -item[2], item[3], item[0]))


def build_and_write_rcsd_road_ownership(
    *,
    step_root: Any,
    rcsd_roads: list[dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    swsd_segments: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    connectivity_supplement_road_ids: set[str],
    special_junction_ids_by_road: dict[str, list[str]] | None = None,
    canonicalizer: NodeCanonicalizer,
    source_field_name: str,
    rcsd_source_value: int,
) -> OwnershipOutputs:
    special_junction_ids_by_road = special_junction_ids_by_road or {}
    road_by_id = {_feature_id(road): road for road in rcsd_roads if _feature_id(road)}
    final_road_ids_by_original = _final_road_ids_by_original(
        frcsd_roads,
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
    )
    segment_index = _SegmentSpatialIndex(swsd_segments)
    edges = _road_edges(rcsd_roads, canonicalizer)
    attached_segments_by_node = _attached_segments_by_node(
        edges,
        added_road_to_segments,
        excluded_road_ids=connectivity_supplement_road_ids,
    )
    group_rows, group_id_by_road = _connectivity_groups(
        road_by_id=road_by_id,
        edges=edges,
        added_road_to_segments=added_road_to_segments,
        attached_segments_by_node=attached_segments_by_node,
        connectivity_supplement_road_ids=connectivity_supplement_road_ids,
        final_road_ids_by_original=final_road_ids_by_original,
    )
    group_by_id = {
        str(row["properties"]["connectivity_group_id"]): row["properties"]
        for row in group_rows
    }

    ownership_rows: list[dict[str, Any]] = []
    for road_id in sorted(road_by_id):
        road = road_by_id[road_id]
        props = road.get("properties") or {}
        geometry = road.get("geometry")
        final_road_ids = final_road_ids_by_original.get(road_id, [])
        used = bool(final_road_ids)
        mapped_segments = unique_preserve_order(
            str(value) for value in added_road_to_segments.get(road_id, []) if str(value)
        )
        endpoint_segments = _endpoint_related_segments(
            road_id,
            edges=edges,
            attached_segments_by_node=attached_segments_by_node,
        )
        is_advance_right = bool((int(props.get("formway") or 0)) & ADVANCE_RIGHT_FORMWAY_MASK)
        advance_candidates = (
            segment_index.scored_candidates(geometry, segment_type="advance_right")
            if is_advance_right
            else []
        )
        all_candidates = advance_candidates or segment_index.scored_candidates(geometry)
        geometry_candidate_ids = [item[0] for item in all_candidates[:8]]
        candidate_segment_ids = unique_preserve_order(
            [*mapped_segments, *endpoint_segments, *geometry_candidate_ids]
        )

        special_junction_ids = unique_preserve_order(
            str(value)
            for value in special_junction_ids_by_road.get(road_id, [])
            if str(value)
        )
        if special_junction_ids:
            owner_key = f"special_junction:{'|'.join(special_junction_ids)}"
            ownership_rows.append(
                _ownership_feature(
                    road=road,
                    road_id=road_id,
                    owner_type="special_junction_internal",
                    owner_key=owner_key,
                    owner_segment_id="",
                    owner_segment_type="",
                    special_junction_ids=special_junction_ids,
                    related_segment_ids=mapped_segments,
                    candidate_segment_ids=candidate_segment_ids,
                    confidence="exact",
                    evidence_types=["special_junction_group_internal_plan"],
                    reason="RCSD Road is internal to a formally passed special junction group and has no Segment owner",
                    used=used,
                    action="include_context" if used else "hold",
                    final_road_ids=final_road_ids,
                    count_in_segment_metric=False,
                )
            )
            continue

        if advance_candidates:
            owner_segment_id = advance_candidates[0][0]
            ownership_rows.append(
                _ownership_feature(
                    road=road,
                    road_id=road_id,
                    owner_type="single_segment",
                    owner_key=owner_segment_id,
                    owner_segment_id=owner_segment_id,
                    owner_segment_type="advance_right",
                    related_segment_ids=mapped_segments,
                    candidate_segment_ids=candidate_segment_ids,
                    confidence="exact" if advance_candidates[0][1] >= 0.99 else "high",
                    evidence_types=["advance_right_formway", "advance_right_segment_geometry"],
                    reason="RCSD advance-right Road is owned by the best matching SWSD advance-right Segment",
                    used=used,
                    action="include_context" if used else "hold",
                    final_road_ids=final_road_ids,
                    count_in_segment_metric=False,
                )
            )
            continue

        connectivity_group_id = group_id_by_road.get(road_id)
        if connectivity_group_id is not None:
            group = group_by_id[connectivity_group_id]
            related_segment_ids = list(group["related_segment_ids"])
            ownership_rows.append(
                _ownership_feature(
                    road=road,
                    road_id=road_id,
                    owner_type="multi_segment_connectivity",
                    owner_key=connectivity_group_id,
                    owner_segment_id="",
                    owner_segment_type="",
                    connectivity_group_id=connectivity_group_id,
                    related_segment_ids=related_segment_ids,
                    candidate_segment_ids=candidate_segment_ids,
                    confidence="high",
                    evidence_types=["endpoint_attachment", "second_degree_connectivity_group"],
                    reason="RCSD Road belongs to a multi-Segment connectivity supplement group",
                    used=used,
                    action="include_connectivity" if used else "hold",
                    final_road_ids=final_road_ids,
                    count_in_segment_metric=False,
                )
            )
            continue

        if mapped_segments:
            owner_segment_id = _best_segment_id(mapped_segments, all_candidates)
            ownership_rows.append(
                _ownership_feature(
                    road=road,
                    road_id=road_id,
                    owner_type="single_segment",
                    owner_key=owner_segment_id,
                    owner_segment_id=owner_segment_id,
                    owner_segment_type=segment_index.segment_type_by_id.get(owner_segment_id, "normal"),
                    related_segment_ids=[value for value in mapped_segments if value != owner_segment_id],
                    candidate_segment_ids=candidate_segment_ids,
                    confidence="exact" if len(mapped_segments) == 1 else "high",
                    evidence_types=["step3_selected_rcsd_road", "segment_geometry_tiebreak"],
                    reason="RCSD Road is selected by Step3 and assigned to one formal Segment owner",
                    used=used,
                    action="replace_segment" if used else "hold",
                    final_road_ids=final_road_ids,
                    count_in_segment_metric=True,
                    risk_flags=([] if len(mapped_segments) == 1 else ["multiple_carrier_segment_references_collapsed"]),
                )
            )
            continue

        if endpoint_segments:
            owner_segment_id = _best_segment_id(endpoint_segments, all_candidates)
            ownership_rows.append(
                _ownership_feature(
                    road=road,
                    road_id=road_id,
                    owner_type="single_segment",
                    owner_key=owner_segment_id,
                    owner_segment_id=owner_segment_id,
                    owner_segment_type=segment_index.segment_type_by_id.get(owner_segment_id, "normal"),
                    related_segment_ids=[value for value in endpoint_segments if value != owner_segment_id],
                    candidate_segment_ids=candidate_segment_ids,
                    confidence="high",
                    evidence_types=["endpoint_attachment", "segment_geometry_tiebreak"],
                    reason="Unconsumed RCSD Road is attached to an owned Segment corridor",
                    used=used,
                    action="include_context" if used else "hold",
                    final_road_ids=final_road_ids,
                    count_in_segment_metric=False,
                )
            )
            continue

        if all_candidates:
            owner_segment_id = all_candidates[0][0]
            ownership_rows.append(
                _ownership_feature(
                    road=road,
                    road_id=road_id,
                    owner_type="single_segment",
                    owner_key=owner_segment_id,
                    owner_segment_id=owner_segment_id,
                    owner_segment_type=segment_index.segment_type_by_id.get(owner_segment_id, "normal"),
                    related_segment_ids=[],
                    candidate_segment_ids=candidate_segment_ids,
                    confidence="high" if all_candidates[0][1] >= 0.5 else "review_required",
                    evidence_types=["segment_geometry"],
                    reason="RCSD Road is geometrically attributable to one SWSD Segment but was not consumed",
                    used=used,
                    action="include_context" if used else "hold",
                    final_road_ids=final_road_ids,
                    count_in_segment_metric=False,
                    risk_flags=([] if all_candidates[0][1] >= 0.5 else ["weak_geometry_ownership"]),
                )
            )
            continue

        owner_key = f"reality_change:{road_id}"
        ownership_rows.append(
            _ownership_feature(
                road=road,
                road_id=road_id,
                owner_type="reality_change",
                owner_key=owner_key,
                owner_segment_id="",
                owner_segment_type="",
                related_segment_ids=[],
                candidate_segment_ids=[],
                confidence="review_required",
                evidence_types=["all_segment_geometry_exhausted", "endpoint_attachment_absent"],
                reason="No normal or advance-right SWSD Segment is within ownership scope after evidence exhaustion",
                used=used,
                action="include_context" if used else "hold",
                final_road_ids=final_road_ids,
                count_in_segment_metric=False,
                risk_flags=["reality_change_review_required"],
            )
        )

    ownership_paths = write_feature_triplet(
        step_root=step_root,
        stem=RCSD_ROAD_OWNERSHIP_STEM,
        features=ownership_rows,
        fieldnames=RCSD_ROAD_OWNERSHIP_FIELDS,
    )
    connectivity_group_paths = write_feature_triplet(
        step_root=step_root,
        stem=MULTI_SEGMENT_CONNECTIVITY_GROUP_STEM,
        features=group_rows,
        fieldnames=MULTI_SEGMENT_CONNECTIVITY_GROUP_FIELDS,
    )
    summary = _ownership_summary(ownership_rows, group_rows)
    return OwnershipOutputs(
        ownership_rows=ownership_rows,
        connectivity_group_rows=group_rows,
        ownership_paths=ownership_paths,
        connectivity_group_paths=connectivity_group_paths,
        summary=summary,
    )


def sync_segment_relation_ownership_fields(
    segment_relation_rows: list[dict[str, Any]],
    *,
    ownership_rows: list[dict[str, Any]],
    connectivity_group_rows: list[dict[str, Any]],
) -> None:
    owned_by_segment: dict[str, list[str]] = defaultdict(list)
    special_internal_by_segment: dict[str, list[str]] = defaultdict(list)
    ownership_by_final_road_id: dict[str, dict[str, Any]] = {}
    for row in ownership_rows:
        props = row.get("properties") or {}
        if props.get("replacement_status") != "used":
            continue
        final_road_ids = _parse_ids(props.get("final_road_ids")) or [str(props.get("rcsd_road_id") or "")]
        final_road_ids = [value for value in final_road_ids if value]
        for final_road_id in final_road_ids:
            existing = ownership_by_final_road_id.get(final_road_id)
            if existing is not None and existing is not props:
                raise ValueError(f"duplicate ownership decision for final RCSD Road {final_road_id}")
            ownership_by_final_road_id[final_road_id] = props
        if props.get("owner_type") == "single_segment":
            segment_id = str(props.get("owner_segment_id") or "")
            if segment_id:
                owned_by_segment[segment_id].extend(final_road_ids)
        elif props.get("owner_type") == "special_junction_internal":
            for segment_id in _parse_ids(props.get("related_segment_ids")):
                special_internal_by_segment[segment_id].extend(final_road_ids)
    groups_by_segment: dict[str, list[str]] = defaultdict(list)
    roads_by_segment: dict[str, list[str]] = defaultdict(list)
    for row in connectivity_group_rows:
        props = row.get("properties") or {}
        group_id = str(props.get("connectivity_group_id") or "")
        for segment_id in props.get("related_segment_ids") or []:
            segment_id = str(segment_id)
            groups_by_segment[segment_id].append(group_id)
            roads_by_segment[segment_id].extend(str(value) for value in props.get("rcsd_road_ids") or [])
    for row in segment_relation_rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        retained_frcsd_road_ids: list[str] = []
        pruned_frcsd_road_ids: list[str] = []
        for final_road_id in _parse_ids(props.get("frcsd_road_ids")):
            ownership = ownership_by_final_road_id.get(final_road_id)
            if ownership is None:
                retained_frcsd_road_ids.append(final_road_id)
                continue
            if (
                ownership.get("owner_type") == "single_segment"
                and str(ownership.get("owner_segment_id") or "") == segment_id
            ):
                retained_frcsd_road_ids.append(final_road_id)
            else:
                pruned_frcsd_road_ids.append(final_road_id)
        props["frcsd_road_ids"] = unique_preserve_order(retained_frcsd_road_ids)
        props["owned_frcsd_road_ids"] = unique_preserve_order(owned_by_segment.get(segment_id, []))
        props["related_special_junction_internal_road_ids"] = unique_preserve_order(
            special_internal_by_segment.get(segment_id, [])
        )
        props["connectivity_group_ids"] = unique_preserve_order(groups_by_segment.get(segment_id, []))
        props["related_connectivity_road_ids"] = unique_preserve_order(roads_by_segment.get(segment_id, []))
        props["pruned_non_owner_frcsd_road_ids"] = unique_preserve_order(pruned_frcsd_road_ids)
        if pruned_frcsd_road_ids:
            props["risk_flags"] = unique_preserve_order(
                [*_parse_ids(props.get("risk_flags")), "non_owner_frcsd_road_reference_pruned"]
            )


def reconcile_final_road_segment_assignments(
    *,
    frcsd_roads: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    ownership_rows: list[dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any]:
    assignment_by_final_road_id: dict[str, list[str]] = {}
    assignment_by_original_road_id: dict[str, list[str]] = {}
    for row in ownership_rows:
        props = row.get("properties") or {}
        if props.get("replacement_status") != "used":
            continue
        owner_type = str(props.get("owner_type") or "")
        owner_segment_id = str(props.get("owner_segment_id") or "")
        if owner_type == "single_segment":
            if not owner_segment_id:
                raise ValueError(f"single_segment ownership missing owner_segment_id for {props.get('rcsd_road_id')}")
            assignment = [owner_segment_id]
        else:
            assignment = []
        original_road_id = str(props.get("rcsd_road_id") or "")
        if original_road_id:
            assignment_by_original_road_id[original_road_id] = assignment
        for final_road_id in _parse_ids(props.get("final_road_ids")):
            existing = assignment_by_final_road_id.get(final_road_id)
            if existing is not None and existing != assignment:
                raise ValueError(f"conflicting ownership assignments for final RCSD Road {final_road_id}")
            assignment_by_final_road_id[final_road_id] = assignment

    for original_road_id, assignment in assignment_by_original_road_id.items():
        if original_road_id in added_road_to_segments:
            added_road_to_segments[original_road_id] = list(assignment)
    for final_road_id, assignment in assignment_by_final_road_id.items():
        if final_road_id in added_road_to_segments:
            added_road_to_segments[final_road_id] = list(assignment)

    single_count = 0
    unassigned_count = 0
    multi_road_ids: list[str] = []
    for road in frcsd_roads:
        props = road.get("properties") or {}
        if str(props.get(source_field_name)) != str(rcsd_source_value):
            continue
        final_road_id = _feature_id(road)
        if final_road_id in assignment_by_final_road_id:
            props["t06_swsd_segment_ids"] = list(assignment_by_final_road_id[final_road_id])
        segment_ids = _parse_ids(props.get("t06_swsd_segment_ids"))
        if len(segment_ids) > 1:
            multi_road_ids.append(final_road_id)
        elif len(segment_ids) == 1:
            single_count += 1
        else:
            props["t06_swsd_segment_ids"] = []
            unassigned_count += 1

    if multi_road_ids:
        raise ValueError(
            "final RCSD Road multi-Segment assignment is forbidden: "
            + ",".join(sorted(multi_road_ids))
        )
    return {
        "final_rcsd_road_single_segment_assignment_count": single_count,
        "final_rcsd_road_unassigned_count": unassigned_count,
        "final_rcsd_road_multi_segment_assignment_count": 0,
        "final_rcsd_road_multi_segment_assignment_ids": [],
    }


def refresh_rcsd_road_ownership_after_surface(
    *,
    step_root: str | Path,
    summary_path: str | Path,
    swsd_segment_path: str | Path,
    source_field_name: str = "source",
    rcsd_source_value: int = 1,
) -> OwnershipOutputs | None:
    resolved_step_root = Path(step_root)
    resolved_summary_path = Path(summary_path)
    if not resolved_summary_path.is_file():
        return None
    summary_payload = json.loads(resolved_summary_path.read_text(encoding="utf-8"))
    input_paths = summary_payload.get("input_paths") or {}
    rcsdroad_path = Path(str(input_paths.get("rcsdroad_path") or ""))
    rcsdnode_path = Path(str(input_paths.get("rcsdnode_path") or ""))
    frcsd_road_path = resolved_step_root / f"{STEP3_FRCSD_ROAD_STEM}.gpkg"
    added_road_path = resolved_step_root / "t06_step3_added_rcsd_roads.csv"
    relation_path = resolved_step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg"
    connectivity_path = resolved_step_root / f"{MULTI_SEGMENT_CONNECTIVITY_GROUP_STEM}.gpkg"
    required = [rcsdroad_path, rcsdnode_path, frcsd_road_path, added_road_path, relation_path]
    if not all(path.is_file() for path in required):
        return None

    added_road_to_segments: dict[str, list[str]] = {}
    with added_road_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for props in csv.DictReader(handle):
            road_id = str(props.get("entity_id") or "").strip()
            if road_id:
                added_road_to_segments[road_id] = _parse_ids(props.get("swsd_segment_ids"))
    connectivity_supplement_road_ids: set[str] = set()
    if connectivity_path.is_file():
        for row in read_features(connectivity_path):
            props = row.get("properties") or {}
            if str(props.get("connectivity_kind") or "") == "second_degree_bridge":
                connectivity_supplement_road_ids.update(_parse_ids(props.get("rcsd_road_ids")))

    special_junction_ids_by_road: dict[str, list[str]] = defaultdict(list)
    replacement_plan_path_value = input_paths.get("step2_replacement_plan_path")
    special_source_loaded = False
    if replacement_plan_path_value:
        replacement_plan_path = Path(str(replacement_plan_path_value))
        if replacement_plan_path.is_file():
            special_source_loaded = True
            for row in read_features(replacement_plan_path):
                props = row.get("properties") or {}
                if props.get("plan_status") != "ready":
                    continue
                if props.get("execution_action") != "include_context":
                    continue
                if props.get("execution_scope") != "special_junction_group_internal":
                    continue
                special_junction_id = str(props.get("special_junction_id") or "").strip()
                if not special_junction_id:
                    continue
                for road_id in _parse_ids(props.get("rcsd_road_ids")):
                    if special_junction_id not in special_junction_ids_by_road[road_id]:
                        special_junction_ids_by_road[road_id].append(special_junction_id)
    if not special_source_loaded:
        special_audit_path_value = input_paths.get("step2_special_junction_group_audit_path")
        if special_audit_path_value:
            special_audit_path = Path(str(special_audit_path_value))
            if special_audit_path.is_file():
                for row in read_features(special_audit_path):
                    props = row.get("properties") or {}
                    if props.get("gate_status") != "passed":
                        continue
                    special_junction_id = str(props.get("special_junction_id") or "").strip()
                    if not special_junction_id:
                        continue
                    for road_id in _parse_ids(props.get("rcsd_junction_road_ids")):
                        if special_junction_id not in special_junction_ids_by_road[road_id]:
                            special_junction_ids_by_road[road_id].append(special_junction_id)

    rcsd_nodes = read_features(rcsdnode_path)
    frcsd_roads = read_features(frcsd_road_path)
    outputs = build_and_write_rcsd_road_ownership(
        step_root=resolved_step_root,
        rcsd_roads=read_features(rcsdroad_path),
        frcsd_roads=frcsd_roads,
        swsd_segments=read_features(swsd_segment_path),
        added_road_to_segments=added_road_to_segments,
        connectivity_supplement_road_ids=connectivity_supplement_road_ids,
        special_junction_ids_by_road=special_junction_ids_by_road,
        canonicalizer=NodeCanonicalizer.from_node_features(rcsd_nodes),
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
    )
    relation_rows = read_features(relation_path)
    sync_segment_relation_ownership_fields(
        relation_rows,
        ownership_rows=outputs.ownership_rows,
        connectivity_group_rows=outputs.connectivity_group_rows,
    )
    final_assignment_stats = reconcile_final_road_segment_assignments(
        frcsd_roads=frcsd_roads,
        added_road_to_segments=added_road_to_segments,
        ownership_rows=outputs.ownership_rows,
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
    )
    frcsd_road_paths = write_feature_triplet(
        step_root=resolved_step_root,
        stem=STEP3_FRCSD_ROAD_STEM,
        features=frcsd_roads,
        fieldnames=_feature_fieldnames(frcsd_roads, ["id", source_field_name]),
    )
    added_road_rows = [
        feature(
            {
                "entity_id": road_id,
                "entity_type": "road",
                "source": rcsd_source_value,
                "reason": "retained_rcsd_segment_road",
                "swsd_segment_ids": segment_ids,
            },
            None,
        )
        for road_id, segment_ids in sorted(added_road_to_segments.items())
    ]
    added_road_paths = write_feature_triplet(
        step_root=resolved_step_root,
        stem="t06_step3_added_rcsd_roads",
        features=added_road_rows,
        fieldnames=STEP3_CHANGE_AUDIT_FIELDS,
    )
    relation_paths = write_feature_triplet(
        step_root=resolved_step_root,
        stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
        features=relation_rows,
        fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    )
    summary_payload.update(outputs.summary)
    summary_payload.update(final_assignment_stats)
    summary_outputs = dict(summary_payload.get("outputs") or {})
    summary_outputs.update(
        {
            **{f"rcsd_road_ownership_{key}": str(value) for key, value in outputs.ownership_paths.items()},
            **{f"frcsd_road_{key}": str(value) for key, value in frcsd_road_paths.items()},
            **{f"added_rcsd_roads_{key}": str(value) for key, value in added_road_paths.items()},
            **{
                f"multi_segment_connectivity_group_{key}": str(value)
                for key, value in outputs.connectivity_group_paths.items()
            },
            **{f"swsd_frcsd_segment_relation_{key}": str(value) for key, value in relation_paths.items()},
        }
    )
    summary_payload["outputs"] = summary_outputs
    write_json(resolved_summary_path, summary_payload)
    return outputs


def _feature_fieldnames(features: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    fieldnames = list(preferred)
    for row in features:
        for key in (row.get("properties") or {}):
            if key not in fieldnames:
                fieldnames.append(key)
    return fieldnames


def _ownership_feature(
    *,
    road: dict[str, Any],
    road_id: str,
    owner_type: str,
    owner_key: str,
    owner_segment_id: str,
    owner_segment_type: str,
    related_segment_ids: list[str],
    candidate_segment_ids: list[str],
    confidence: str,
    evidence_types: list[str],
    reason: str,
    used: bool,
    action: str,
    final_road_ids: list[str],
    count_in_segment_metric: bool,
    connectivity_group_id: str = "",
    special_junction_ids: list[str] | None = None,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    return feature(
        {
            "rcsd_road_id": road_id,
            "owner_type": owner_type,
            "owner_key": owner_key,
            "owner_segment_id": owner_segment_id,
            "owner_segment_type": owner_segment_type,
            "connectivity_group_id": connectivity_group_id,
            "special_junction_ids": special_junction_ids or [],
            "related_segment_ids": related_segment_ids,
            "candidate_segment_ids": candidate_segment_ids,
            "ownership_status": "resolved",
            "ownership_confidence": confidence,
            "ownership_evidence_types": evidence_types,
            "ownership_reason": reason,
            "replacement_status": "used" if used else "not_used",
            "replacement_action": action,
            "final_road_ids": final_road_ids,
            "risk_flags": risk_flags or [],
            "count_in_rcsd_road_metric": used,
            "count_in_segment_metric": count_in_segment_metric and used,
        },
        road.get("geometry"),
    )


def _connectivity_groups(
    *,
    road_by_id: dict[str, dict[str, Any]],
    edges: dict[str, tuple[str, str]],
    added_road_to_segments: dict[str, list[str]],
    attached_segments_by_node: dict[str, set[str]],
    connectivity_supplement_road_ids: set[str],
    final_road_ids_by_original: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    formal_road_ids = {
        road_id
        for road_id in connectivity_supplement_road_ids
        if road_id in edges and not _is_advance_right_road(road_by_id.get(road_id))
    }
    candidate_direct_ids: set[str] = set()
    for road_id, edge in edges.items():
        if road_id in added_road_to_segments:
            continue
        if _is_advance_right_road(road_by_id.get(road_id)):
            continue
        left = attached_segments_by_node.get(edge[0], set())
        right = attached_segments_by_node.get(edge[1], set())
        if left and right and len(left | right) >= 2:
            candidate_direct_ids.add(road_id)
    components = _connected_road_components(formal_road_ids | candidate_direct_ids, edges)
    rows: list[dict[str, Any]] = []
    group_id_by_road: dict[str, str] = {}
    for road_ids in components:
        related_segment_ids = unique_preserve_order(
            segment_id
            for road_id in road_ids
            for segment_id in (
                added_road_to_segments.get(road_id, [])
                or _endpoint_related_segments(
                    road_id,
                    edges=edges,
                    attached_segments_by_node=attached_segments_by_node,
                )
            )
        )
        if len(related_segment_ids) < 2:
            continue
        digest = sha1("\x1f".join(sorted(road_ids)).encode("utf-8")).hexdigest()[:16]
        group_id = f"connectivity_{digest}"
        terminal_node_ids = _component_terminal_nodes(road_ids, edges)
        used = any(final_road_ids_by_original.get(road_id) for road_id in road_ids)
        connectivity_kind = (
            "second_degree_bridge"
            if any(road_id in connectivity_supplement_road_ids for road_id in road_ids)
            else "other_reviewed"
        )
        geometry = _union_geometry([road_by_id[road_id].get("geometry") for road_id in road_ids if road_id in road_by_id])
        rows.append(
            feature(
                {
                    "connectivity_group_id": group_id,
                    "connectivity_kind": connectivity_kind,
                    "rcsd_road_ids": road_ids,
                    "final_road_ids": unique_preserve_order(
                        final_id
                        for road_id in road_ids
                        for final_id in final_road_ids_by_original.get(road_id, [])
                    ),
                    "terminal_node_ids": terminal_node_ids,
                    "related_segment_ids": related_segment_ids,
                    "terminal_attachment_evidence": [
                        f"{node_id}:{','.join(sorted(attached_segments_by_node.get(node_id, set())))}"
                        for node_id in terminal_node_ids
                    ],
                    "connectivity_status": "attachable",
                    "replacement_status": "used" if used else "not_used",
                    "blocked_reason": "",
                    "risk_flags": ["connectivity_supplement_not_segment_replacement"],
                    "count_in_rcsd_road_metric": used,
                    "count_in_segment_metric": False,
                },
                geometry,
            )
        )
        for road_id in road_ids:
            group_id_by_road[road_id] = group_id
    return rows, group_id_by_road


def _ownership_summary(
    ownership_rows: list[dict[str, Any]],
    connectivity_group_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    props_rows = [row.get("properties") or {} for row in ownership_rows]
    road_ids = [str(props.get("rcsd_road_id") or "") for props in props_rows]
    duplicate_count = len(road_ids) - len(set(road_ids))
    used_rows = [row for row in ownership_rows if (row.get("properties") or {}).get("replacement_status") == "used"]
    return {
        "rcsd_road_total_count": len(ownership_rows),
        "rcsd_road_used_count": len(used_rows),
        "rcsd_road_used_length_m": round(
            sum(float(getattr(row.get("geometry"), "length", 0.0) or 0.0) for row in used_rows),
            3,
        ),
        "connectivity_group_count": len(connectivity_group_rows),
        "connectivity_group_used_count": sum(
            1
            for row in connectivity_group_rows
            if (row.get("properties") or {}).get("replacement_status") == "used"
        ),
        "connectivity_rcsd_road_used_count": sum(
            1
            for props in props_rows
            if props.get("owner_type") == "multi_segment_connectivity" and props.get("replacement_status") == "used"
        ),
        "special_junction_internal_rcsd_road_count": sum(
            1 for props in props_rows if props.get("owner_type") == "special_junction_internal"
        ),
        "special_junction_internal_rcsd_road_used_count": sum(
            1
            for props in props_rows
            if props.get("owner_type") == "special_junction_internal"
            and props.get("replacement_status") == "used"
        ),
        "reality_change_rcsd_road_count": sum(1 for props in props_rows if props.get("owner_type") == "reality_change"),
        "unresolved_exception_rcsd_road_count": sum(
            1 for props in props_rows if props.get("owner_type") == "unresolved_exception"
        ),
        "ownership_duplicate_count": duplicate_count,
        "ownership_missing_count": 0,
        "advance_right_segment_used_count": len(
            {
                str(props.get("owner_segment_id"))
                for props in props_rows
                if props.get("owner_segment_type") == "advance_right"
                and props.get("replacement_status") == "used"
            }
        ),
        "advance_right_rcsd_road_used_count": sum(
            1
            for props in props_rows
            if props.get("owner_segment_type") == "advance_right"
            and props.get("replacement_status") == "used"
        ),
    }


def _final_road_ids_by_original(
    frcsd_roads: list[dict[str, Any]],
    *,
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in frcsd_roads:
        props = road.get("properties") or {}
        if str(props.get(source_field_name)) != str(rcsd_source_value):
            continue
        final_id = _feature_id(road)
        if not final_id:
            continue
        original_ids = [final_id]
        for field_name in ("source_road_id", "t06_split_original_road_id", "t06_mixed_advance_right_rcsd_road_ids"):
            original_ids.extend(_parse_ids(props.get(field_name)))
        for original_id in unique_preserve_order(original_ids):
            if final_id not in result[original_id]:
                result[original_id].append(final_id)
    return dict(result)


def _best_segment_id(segment_ids: list[str], scored: list[tuple[str, float, float, float]]) -> str:
    allowed = set(segment_ids)
    for segment_id, _cover20, _cover50, _distance in scored:
        if segment_id in allowed:
            return segment_id
    return sorted(allowed)[0]


def _road_edges(
    roads: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for road in roads:
        road_id = _feature_id(road)
        props = road.get("properties") or {}
        try:
            endpoints = (
                canonicalizer.canonicalize(props.get("snodeid")),
                canonicalizer.canonicalize(props.get("enodeid")),
            )
        except ParseError:
            continue
        if road_id and endpoints[0] != endpoints[1]:
            result[road_id] = endpoints
    return result


def _attached_segments_by_node(
    edges: dict[str, tuple[str, str]],
    added_road_to_segments: dict[str, list[str]],
    *,
    excluded_road_ids: set[str],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for road_id, segment_ids in added_road_to_segments.items():
        if road_id in excluded_road_ids or road_id not in edges:
            continue
        for node_id in edges[road_id]:
            result[node_id].update(str(value) for value in segment_ids if str(value))
    return dict(result)


def _endpoint_related_segments(
    road_id: str,
    *,
    edges: dict[str, tuple[str, str]],
    attached_segments_by_node: dict[str, set[str]],
) -> list[str]:
    edge = edges.get(road_id)
    if edge is None:
        return []
    return sorted(attached_segments_by_node.get(edge[0], set()) | attached_segments_by_node.get(edge[1], set()))


def _connected_road_components(
    road_ids: set[str],
    edges: dict[str, tuple[str, str]],
) -> list[list[str]]:
    road_ids_by_node: dict[str, set[str]] = defaultdict(set)
    for road_id in road_ids:
        if road_id not in edges:
            continue
        for node_id in edges[road_id]:
            road_ids_by_node[node_id].add(road_id)
    pending = set(road_ids)
    components: list[list[str]] = []
    while pending:
        seed = min(pending)
        pending.remove(seed)
        queue = [seed]
        component: list[str] = []
        while queue:
            road_id = queue.pop(0)
            component.append(road_id)
            for node_id in edges.get(road_id, ()):
                for next_road_id in road_ids_by_node[node_id]:
                    if next_road_id in pending:
                        pending.remove(next_road_id)
                        queue.append(next_road_id)
        components.append(sorted(component))
    return components


def _component_terminal_nodes(road_ids: list[str], edges: dict[str, tuple[str, str]]) -> list[str]:
    degree: dict[str, int] = defaultdict(int)
    for road_id in road_ids:
        for node_id in edges.get(road_id, ()):
            degree[node_id] += 1
    return sorted(node_id for node_id, value in degree.items() if value == 1)


def _union_geometry(geometries: list[Any]) -> Any:
    usable = [geometry for geometry in geometries if _usable_geometry(geometry)]
    if not usable:
        return None
    result = usable[0]
    for geometry in usable[1:]:
        result = result.union(geometry)
    return result


def _coverage_ratio(road_geometry: Any, segment_geometry: Any, buffer_m: float) -> float:
    length = float(road_geometry.length or 0.0)
    if length <= 0.0:
        return 0.0
    try:
        covered = float(road_geometry.intersection(segment_geometry.buffer(buffer_m)).length)
    except Exception:
        return 0.0
    return min(1.0, max(0.0, covered / length))


def _usable_geometry(geometry: Any) -> bool:
    return geometry is not None and not bool(getattr(geometry, "is_empty", True)) and hasattr(geometry, "buffer")


def _is_advance_right_road(road: dict[str, Any] | None) -> bool:
    props = (road or {}).get("properties") or {}
    try:
        formway = int(props.get("formway") or 0)
    except (TypeError, ValueError):
        formway = 0
    return bool(formway & ADVANCE_RIGHT_FORMWAY_MASK)


def _feature_id(row: dict[str, Any]) -> str:
    try:
        return normalize_id((row.get("properties") or {}).get("id"))
    except ParseError:
        return ""


def _parse_ids(value: Any) -> list[str]:
    try:
        parsed = parse_id_list(value, allow_empty=True)
    except ParseError:
        parsed = []
    if parsed:
        return parsed
    text = str(value or "").strip()
    return [text] if text else []
