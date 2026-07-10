from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorReadResult,
    get_case_insensitive_property,
    read_vector,
    resolve_case_insensitive_field_name,
    resolve_field_name,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    RestrictionInput,
    RestorationStrategy,
    RoadAttributes,
    SWSDSegmentInput,
    SWSDRoadInput,
    T09SwsdArm,
    normalize_restoration_strategy,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    restriction_condition_identity,
)


@dataclass(frozen=True)
class T09LoadedInputs:
    junction_member_node_ids: dict[str, tuple[str, ...]]
    roads: tuple[SWSDRoadInput, ...]
    road_attributes: tuple[RoadAttributes, ...]
    segments: tuple[SWSDSegmentInput, ...]
    segment_geometries: dict[str, BaseGeometry]
    restrictions: tuple[RestrictionInput, ...]
    arrows: tuple[ArrowInput, ...]
    road_geometries: dict[str, BaseGeometry]
    input_audit: dict[str, Any]
    crs_transform_executed: bool


def load_t09_inputs(
    *,
    swnode_gpkg: str | Path,
    swroad_gpkg: str | Path,
    segment_gpkg: str | Path | None = None,
    restriction_gpkg: str | Path | None = None,
    arrow_gpkg: str | Path | None = None,
    swnode_layer: str | None = None,
    swroad_layer: str | None = None,
    segment_layer: str | None = None,
    restriction_layer: str | None = None,
    arrow_layer: str | None = None,
    target_epsg: int = 3857,
    swnode_default_crs_text: str | None = None,
    swroad_default_crs_text: str | None = None,
    segment_default_crs_text: str | None = None,
    restriction_default_crs_text: str | None = None,
    arrow_default_crs_text: str | None = None,
    strategy_version: str | RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1,
) -> T09LoadedInputs:
    strategy = normalize_restoration_strategy(strategy_version)
    node_result = read_vector(
        swnode_gpkg,
        layer_name=swnode_layer,
        default_crs_text=swnode_default_crs_text,
        target_epsg=target_epsg,
    )
    road_result = read_vector(
        swroad_gpkg,
        layer_name=swroad_layer,
        default_crs_text=swroad_default_crs_text,
        target_epsg=target_epsg,
    )
    segment_result = (
        read_vector(
            segment_gpkg,
            layer_name=segment_layer,
            default_crs_text=segment_default_crs_text,
            target_epsg=target_epsg,
        )
        if segment_gpkg is not None
        else None
    )
    restriction_result = (
        read_vector(
            restriction_gpkg,
            layer_name=restriction_layer,
            default_crs_text=restriction_default_crs_text,
            target_epsg=target_epsg,
        )
        if restriction_gpkg is not None
        else None
    )
    arrow_result = (
        read_vector(
            arrow_gpkg,
            layer_name=arrow_layer,
            default_crs_text=arrow_default_crs_text,
            target_epsg=target_epsg,
        )
        if arrow_gpkg is not None
        else None
    )

    junctions, node_audit = _read_kind2_junctions(node_result)
    roads, road_attrs, road_geometries, road_audit = _read_swsd_roads(road_result)
    segments, segment_geometries, segment_audit = (
        _read_segments(segment_result) if segment_result else (tuple(), {}, {})
    )
    restrictions, restriction_audit = (
        _read_tool7_restrictions(restriction_result) if restriction_result else (tuple(), {})
    )
    arrows, arrow_audit = (
        _read_tool8_arrows(
            arrow_result,
            roads_by_id={road.road_id: road for road in roads},
            strict_metadata=strategy == RestorationStrategy.MULTI_EVIDENCE_V2,
        )
        if arrow_result
        else (tuple(), {})
    )
    input_results = tuple(
        item
        for item in (node_result, road_result, segment_result, restriction_result, arrow_result)
        if item is not None
    )
    return T09LoadedInputs(
        junction_member_node_ids=junctions,
        roads=roads,
        road_attributes=road_attrs,
        segments=segments,
        segment_geometries=segment_geometries,
        restrictions=restrictions,
        arrows=arrows,
        road_geometries=road_geometries,
        input_audit={
            "target_epsg": target_epsg,
            "nodes": node_audit | _layer_audit(node_result),
            "roads": road_audit | _layer_audit(road_result),
            "segments": segment_audit | (_layer_audit(segment_result) if segment_result else {}),
            "restrictions": restriction_audit | (_layer_audit(restriction_result) if restriction_result else {}),
            "arrows": arrow_audit | (_layer_audit(arrow_result) if arrow_result else {}),
        },
        crs_transform_executed=any(item.source_crs != item.output_crs for item in input_results),
    )


def annotate_arm_angles(
    arms: tuple[T09SwsdArm, ...],
    *,
    roads_by_id: dict[str, SWSDRoadInput],
    road_geometries: dict[str, BaseGeometry],
) -> tuple[T09SwsdArm, ...]:
    from dataclasses import replace

    annotated: list[T09SwsdArm] = []
    for arm in arms:
        angles = []
        for seed_id in arm.seed_road_ids:
            road = roads_by_id.get(seed_id)
            geometry = road_geometries.get(seed_id)
            angle = _arm_outward_angle(road, geometry, set(arm.member_node_ids)) if road and geometry else None
            if angle is not None:
                angles.append(angle)
        angle = _mean_angle(angles)
        audit_refs = arm.audit_refs + ((f"angle_deg={angle:.6f}" if angle is not None else "angle_missing"),)
        annotated.append(replace(arm, angle_deg=angle, audit_refs=audit_refs))
    return tuple(annotated)


def _read_kind2_junctions(result: VectorReadResult) -> tuple[dict[str, tuple[str, ...]], dict[str, Any]]:
    id_field = _required_field(result, ["id", "nodeid", "node_id"], "SWSD node")
    kind2_field = _required_field(result, ["kind_2"], "SWSD node")
    mainnode_field = _optional_field(result, ["mainnodeid", "main_node_id"])
    groups: dict[str, list[str]] = {}
    group_has_kind2_4: dict[str, bool] = {}
    for feature in result.features:
        node_id = _normalize_id(feature.properties.get(id_field))
        if node_id is None:
            raise ValueError(f"SWSD node has empty id in {result.path}")
        mainnode_id = _normalize_id(feature.properties.get(mainnode_field)) if mainnode_field else None
        group_id = mainnode_id if _has_effective_mainnodeid(mainnode_id) else node_id
        groups.setdefault(group_id, []).append(node_id)
        if _parse_int(feature.properties.get(kind2_field)) == 4:
            group_has_kind2_4[group_id] = True
    junctions = {
        group_id: tuple(sorted(member_ids, key=_sort_key))
        for group_id, member_ids in groups.items()
        if group_has_kind2_4.get(group_id, False)
    }
    return junctions, {
        "id_field": id_field,
        "mainnodeid_field": mainnode_field,
        "kind_2_field": kind2_field,
        "kind_2_4_junction_count": len(junctions),
    }


def _read_swsd_roads(
    result: VectorReadResult,
) -> tuple[tuple[SWSDRoadInput, ...], tuple[RoadAttributes, ...], dict[str, BaseGeometry], dict[str, Any]]:
    id_field = _required_field(result, ["id", "linkid", "LinkID"], "SWSD road")
    snode_field = _required_field(result, ["snodeid", "snode_id", "startnodeid"], "SWSD road")
    enode_field = _required_field(result, ["enodeid", "enode_id", "endnodeid"], "SWSD road")
    direction_field = _required_field(result, ["direction", "Direction"], "SWSD road")
    kind_field = _optional_field(result, ["kind", "Kind"])
    formway_field = _optional_field(result, ["formway", "Formway"])
    segmentid_field = _optional_field(result, ["segmentid", "segment_id"])
    roads: list[SWSDRoadInput] = []
    attrs: list[RoadAttributes] = []
    geometries: dict[str, BaseGeometry] = {}
    missing_endpoint_count = 0
    for feature in result.features:
        road_id = _required_id(feature.properties.get(id_field), f"SWSD road id in {result.path}")
        snodeid = _required_id(feature.properties.get(snode_field), f"SWSD road snodeid for {road_id}")
        enodeid = _required_id(feature.properties.get(enode_field), f"SWSD road enodeid for {road_id}")
        direction = _parse_int(feature.properties.get(direction_field))
        if direction is None:
            raise ValueError(f"SWSD road direction is not parseable for road {road_id}")
        if not snodeid or not enodeid:
            missing_endpoint_count += 1
        kind = _normalize_optional_text(feature.properties.get(kind_field)) if kind_field else None
        formway = _parse_int(feature.properties.get(formway_field)) if formway_field else 0
        segment_ids = _parse_id_list(feature.properties.get(segmentid_field)) if segmentid_field else tuple()
        roads.append(
            SWSDRoadInput(
                road_id=road_id,
                snodeid=snodeid,
                enodeid=enodeid,
                direction=direction,
                kind=kind,
                formway=formway or 0,
                segment_ids=segment_ids,
            )
        )
        attrs.append(RoadAttributes(road_id=road_id, kind=kind, formway=formway or 0))
        geometries[road_id] = feature.geometry
    return tuple(roads), tuple(attrs), geometries, {
        "id_field": id_field,
        "snodeid_field": snode_field,
        "enodeid_field": enode_field,
        "direction_field": direction_field,
        "kind_field": kind_field,
        "formway_field": formway_field,
        "segmentid_field": segmentid_field,
        "missing_endpoint_count": missing_endpoint_count,
    }


def _read_segments(
    result: VectorReadResult,
) -> tuple[tuple[SWSDSegmentInput, ...], dict[str, BaseGeometry], dict[str, Any]]:
    id_field = _required_field(result, ["id", "segmentid", "segment_id"], "T01 segment")
    pair_nodes_field = _required_field(result, ["pair_nodes"], "T01 segment")
    junc_nodes_field = _required_field(result, ["junc_nodes"], "T01 segment")
    roads_field = _required_field(result, ["roads", "road_ids"], "T01 segment")
    sgrade_field = _optional_field(result, ["sgrade"])
    segments: list[SWSDSegmentInput] = []
    geometries: dict[str, BaseGeometry] = {}
    for feature in result.features:
        segment_id = _required_id(feature.properties.get(id_field), f"T01 segment id in {result.path}")
        segments.append(
            SWSDSegmentInput(
                segment_id=segment_id,
                pair_nodes=_parse_id_list(feature.properties.get(pair_nodes_field)),
                junc_nodes=_parse_id_list(feature.properties.get(junc_nodes_field)),
                road_ids=_parse_id_list(feature.properties.get(roads_field)),
                sgrade=_normalize_optional_text(feature.properties.get(sgrade_field)) if sgrade_field else None,
            )
        )
        geometries[segment_id] = feature.geometry
    return tuple(segments), geometries, {
        "id_field": id_field,
        "pair_nodes_field": pair_nodes_field,
        "junc_nodes_field": junc_nodes_field,
        "roads_field": roads_field,
        "sgrade_field": sgrade_field,
        "segment_count": len(segments),
    }


def _read_tool7_restrictions(result: VectorReadResult) -> tuple[tuple[RestrictionInput, ...], dict[str, Any]]:
    in_link_field = _required_field(result, ["inLinkID", "inlinkid"], "T08 Tool7 restriction")
    out_link_field = _required_field(result, ["outLinkID", "outlinkid"], "T08 Tool7 restriction")
    id_field = _optional_field(result, ["id", "restriction_id", "CondID", "condid", "cond_id"])
    condition_type_field = _optional_field(result, ["CondType", "condtype", "condition_type"])
    restrictions: list[RestrictionInput] = []
    for index, feature in enumerate(result.features, start=1):
        in_link = _required_id(feature.properties.get(in_link_field), f"Tool7 inLinkID row {index}")
        out_link = _required_id(feature.properties.get(out_link_field), f"Tool7 outLinkID row {index}")
        source_id = _normalize_id(feature.properties.get(id_field)) if id_field else None
        raw_properties = dict(feature.properties)
        restriction = RestrictionInput(
            restriction_id=source_id or f"tool7:{index}",
            in_link_id=in_link,
            out_link_id=out_link,
            properties=raw_properties,
            geometry=feature.geometry,
            condition_type=(
                _normalize_optional_text(feature.properties.get(condition_type_field))
                if condition_type_field
                else None
            ),
            condition_payload=raw_properties,
            condition_semantics_status="unknown",
        )
        restrictions.append(
            replace(
                restriction,
                condition_identity=restriction_condition_identity(restriction),
            )
        )
    return tuple(restrictions), {
        "id_field": id_field,
        "in_link_field": in_link_field,
        "out_link_field": out_link_field,
        "condition_type_field": condition_type_field,
        "condition_identity_count": len({item.condition_identity for item in restrictions}),
        "restriction_count": len(restrictions),
    }


def _read_tool8_arrows(
    result: VectorReadResult,
    *,
    roads_by_id: dict[str, SWSDRoadInput],
    strict_metadata: bool,
) -> tuple[tuple[ArrowInput, ...], dict[str, Any]]:
    link_field = _required_field(result, ["linkid", "LinkID"], "T08 Tool8 arrow")
    arrow_field = _required_field(result, ["arrow"], "T08 Tool8 arrow")
    lane_count_field = _optional_field(result, ["lane_count"])
    lane_dir_field = _optional_field(result, ["lane_dir", "Lane_Dir"])
    road_direction_field = _optional_field(result, ["road_direction", "direction"])
    seq_start_field = _optional_field(result, ["seq_start"])
    seq_end_field = _optional_field(result, ["seq_end"])
    source_arrow_dir_field = _optional_field(result, ["source_arrow_dir"])
    id_field = _optional_field(result, ["id", "arrow_id"])
    arrows: list[ArrowInput] = []
    incomplete_count = 0
    direction_mismatch_count = 0
    sequence_metadata_status_counts: dict[str, int] = {}
    for index, feature in enumerate(result.features, start=1):
        link_id = _required_id(feature.properties.get(link_field), f"Tool8 linkid row {index}")
        lane_codes = _parse_arrow_codes(feature.properties.get(arrow_field))
        lane_count = _parse_int(feature.properties.get(lane_count_field)) if lane_count_field else None
        lane_dir = _parse_int(feature.properties.get(lane_dir_field)) if lane_dir_field else None
        road_direction = (
            _parse_int(feature.properties.get(road_direction_field)) if road_direction_field else None
        )
        seq_start = _parse_int(feature.properties.get(seq_start_field)) if seq_start_field else None
        seq_end = _parse_int(feature.properties.get(seq_end_field)) if seq_end_field else None
        source_arrow_dir = (
            _normalize_optional_text(feature.properties.get(source_arrow_dir_field))
            if source_arrow_dir_field
            else None
        )
        explicit_complete = get_case_insensitive_property(
            feature.properties,
            ["lane_sequence_complete", "sequence_complete"],
        )
        strict_sequence_complete, sequence_metadata_status = _tool8_sequence_complete(
            lane_codes=lane_codes,
            lane_count=lane_count,
            seq_start=seq_start,
            seq_end=seq_end,
            source_arrow_dir=source_arrow_dir,
            explicit_complete=explicit_complete,
        )
        legacy_sequence_complete = bool(lane_codes)
        if lane_count is not None and lane_count != len(lane_codes):
            legacy_sequence_complete = False
        if explicit_complete is not None:
            legacy_sequence_complete = _parse_bool(explicit_complete)
        lane_sequence_complete = (
            strict_sequence_complete if strict_metadata else legacy_sequence_complete
        )
        if not lane_sequence_complete:
            incomplete_count += 1
        sequence_metadata_status_counts[sequence_metadata_status] = (
            sequence_metadata_status_counts.get(sequence_metadata_status, 0) + 1
        )
        strict_direction_matched = _tool8_direction_matches_swsd_road(
            lane_dir=lane_dir,
            arrow_road_direction=road_direction,
            swsd_road=roads_by_id.get(link_id),
        )
        direction_matched = strict_direction_matched if strict_metadata else True
        if not direction_matched:
            direction_mismatch_count += 1
        source_id = _normalize_id(feature.properties.get(id_field)) if id_field else None
        arrows.append(
            ArrowInput(
                arrow_id=source_id or f"tool8:{index}:{link_id}",
                road_id=link_id,
                lane_codes=lane_codes,
                direction_matched=direction_matched,
                lane_sequence_complete=lane_sequence_complete,
                geometry_match_method="t08_tool8_linkid_directional_geometry",
                properties=dict(feature.properties),
                source_feature_id=source_id,
                geometry=feature.geometry,
                lane_dir=lane_dir,
                road_direction=road_direction,
                seq_start=seq_start,
                seq_end=seq_end,
                source_arrow_dir=source_arrow_dir,
                sequence_metadata_status=sequence_metadata_status,
            )
        )
    return tuple(arrows), {
        "id_field": id_field,
        "link_field": link_field,
        "arrow_field": arrow_field,
        "lane_count_field": lane_count_field,
        "lane_dir_field": lane_dir_field,
        "road_direction_field": road_direction_field,
        "seq_start_field": seq_start_field,
        "seq_end_field": seq_end_field,
        "source_arrow_dir_field": source_arrow_dir_field,
        "arrow_count": len(arrows),
        "incomplete_arrow_count": incomplete_count,
        "direction_mismatch_count": direction_mismatch_count,
        "sequence_metadata_status_counts": sequence_metadata_status_counts,
    }


def _tool8_sequence_complete(
    *,
    lane_codes: tuple[str, ...],
    lane_count: int | None,
    seq_start: int | None,
    seq_end: int | None,
    source_arrow_dir: str | None,
    explicit_complete: Any,
) -> tuple[bool, str]:
    if explicit_complete is not None and not _parse_bool(explicit_complete):
        return False, "explicit_incomplete"
    if not lane_codes:
        return False, "empty_arrow_sequence"
    if lane_count is None or seq_start is None or seq_end is None or source_arrow_dir is None:
        return False, "sequence_metadata_missing"
    if lane_count <= 0 or lane_count != len(lane_codes):
        return False, "lane_count_mismatch"
    source_record_count = len(tuple(item for item in source_arrow_dir.split("|") if item.strip()))
    if source_record_count <= 0:
        return False, "source_record_count_missing"
    if seq_start != 1 or seq_end < seq_start:
        return False, "sequence_range_invalid"
    if seq_end - seq_start + 1 != source_record_count:
        return False, "sequence_range_source_count_mismatch"
    if source_record_count > lane_count:
        return False, "source_record_lane_count_mismatch"
    return True, "complete"


def _tool8_direction_matches_swsd_road(
    *,
    lane_dir: int | None,
    arrow_road_direction: int | None,
    swsd_road: SWSDRoadInput | None,
) -> bool:
    if lane_dir not in {2, 3} or arrow_road_direction not in {0, 1, 2, 3}:
        return False
    if swsd_road is not None and arrow_road_direction != swsd_road.direction:
        return False
    effective_road_direction = swsd_road.direction if swsd_road is not None else arrow_road_direction
    if effective_road_direction in {0, 1}:
        return True
    return lane_dir == effective_road_direction


def _layer_audit(result: VectorReadResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "path": str(result.path),
        "layer_name": result.layer_name,
        "feature_count": len(result.features),
        "field_names": list(result.field_names),
        "source_crs": result.source_crs.to_string(),
        "output_crs": result.output_crs.to_string(),
        "crs_source": result.crs_source,
    }


def _optional_field(result: VectorReadResult, candidates: list[str]) -> str | None:
    for feature in result.features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    resolved = resolve_case_insensitive_field_name({field_name: None for field_name in result.field_names}, candidates)
    if resolved is not None:
        return resolved
    return None


def _required_field(result: VectorReadResult, candidates: list[str], label: str) -> str:
    if result.features:
        return resolve_field_name(result.features, candidates, label)
    resolved = resolve_case_insensitive_field_name({field_name: None for field_name in result.field_names}, candidates)
    if resolved is None:
        raise ValueError(f"Required field {candidates} not found in {label}")
    return resolved


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _required_id(value: Any, label: str) -> str:
    normalized = _normalize_id(value)
    if normalized is None:
        raise ValueError(f"Required id is empty: {label}")
    return normalized


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _has_effective_mainnodeid(value: str | None) -> bool:
    return value is not None and value not in {"0", "0.0"}


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if number.is_integer() else None


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _parse_id_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return tuple()
    if isinstance(value, (list, tuple, set)):
        return tuple(item for item in (_normalize_id(raw) for raw in value) if item is not None)
    text = str(value).strip()
    if not text:
        return tuple()
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return tuple(item for item in (_normalize_id(raw) for raw in parsed) if item is not None)
    separators = [",", "|", ";"]
    values = [text]
    for separator in separators:
        if separator in text:
            values = text.split(separator)
            break
    return tuple(item for item in (_normalize_id(raw) for raw in values) if item is not None)


def _parse_arrow_codes(value: Any) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def _arm_outward_angle(
    road: SWSDRoadInput,
    geometry: BaseGeometry,
    member_nodes: set[str],
) -> float | None:
    coords = _line_coords(geometry)
    if len(coords) < 2:
        return None
    if road.snodeid in member_nodes and road.enodeid not in member_nodes:
        start, end = coords[0], coords[-1]
    elif road.enodeid in member_nodes and road.snodeid not in member_nodes:
        start, end = coords[-1], coords[0]
    else:
        return None
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return None
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _mean_angle(angles: list[float]) -> float | None:
    if not angles:
        return None
    x = sum(math.cos(math.radians(angle)) for angle in angles)
    y = sum(math.sin(math.radians(angle)) for angle in angles)
    if abs(x) <= 1e-12 and abs(y) <= 1e-12:
        return angles[0]
    return math.degrees(math.atan2(y, x)) % 360.0


def _line_coords(geometry: BaseGeometry) -> list[tuple[float, float]]:
    if isinstance(geometry, LineString):
        return [(float(x), float(y)) for x, y, *_rest in geometry.coords]
    if isinstance(geometry, MultiLineString):
        parts = [part for part in geometry.geoms if not part.is_empty]
        if not parts:
            return []
        longest = max(parts, key=lambda part: float(part.length))
        return [(float(x), float(y)) for x, y, *_rest in longest.coords]
    return []


def _sort_key(value: str) -> tuple[int, Any]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
