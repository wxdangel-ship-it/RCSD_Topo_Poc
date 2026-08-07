from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Mapping, Sequence

from pyproj import CRS
from shapely.geometry import LineString, Point
from shapely.ops import substring

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    RoadRole,
    RoadSource,
    SegmentDecision,
)


FORWARD_DIRECTIONS = frozenset({0, 1, 2})
REVERSE_DIRECTIONS = frozenset({0, 1, 3})


class MaterializationError(ValueError):
    """A declared model/ledger operation cannot be executed without repair."""


class NodeRecipeKind(str, Enum):
    COPY_SOURCE_NODE = "COPY_SOURCE_NODE"
    INTERPOLATE_SOURCE_ROAD = "INTERPOLATE_SOURCE_ROAD"


class GeometryJoinMode(str, Enum):
    COINCIDENT_ONLY = "COINCIDENT_ONLY"
    STRAIGHT_CONNECTOR = "STRAIGHT_CONNECTOR"


class SegmentMaterializationType(str, Enum):
    STANDARD = "STANDARD"
    ADVANCE_RIGHT = "ADVANCE_RIGHT"


class AttachmentEndpoint(str, Enum):
    SOURCE = "SOURCE"
    TARGET = "TARGET"


class AccessStructuralRole(str, Enum):
    ENDPOINT = "ENDPOINT"
    THROUGH = "THROUGH"
    ADVANCE_RIGHT_ATTACHMENT = "ADVANCE_RIGHT_ATTACHMENT"


class AccessDirectionRole(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    BOTH = "BOTH"
    UNKNOWN = "UNKNOWN"


class AttachmentTargetKind(str, Enum):
    ROAD_POSITION = "ROAD_POSITION"
    FROZEN_ACCESS_NODE = "FROZEN_ACCESS_NODE"


@dataclass(frozen=True)
class SourceRoadRecord:
    source_kind: RoadSource
    source_road_id: str
    geometry: LineString
    start_node_id: str
    end_node_id: str
    direction: int
    crs: str
    properties: Mapping[str, Any] | None = None

    def validate(self, expected_crs: str) -> None:
        if not self.source_road_id or not self.start_node_id or not self.end_node_id:
            raise MaterializationError("source Road identity/endpoints are incomplete")
        if not isinstance(self.geometry, LineString):
            raise MaterializationError("source Road must be a LineString")
        if self.geometry.is_empty or not self.geometry.is_valid:
            raise MaterializationError("source Road geometry is empty or invalid")
        if self.geometry.length <= 0:
            raise MaterializationError("source Road geometry has zero length")
        if self.direction not in FORWARD_DIRECTIONS | REVERSE_DIRECTIONS:
            raise MaterializationError("source Road direction is outside the formal enum")
        if _canonical_crs(self.crs) != _canonical_crs(expected_crs):
            raise MaterializationError("source Road CRS differs from the materializer CRS")


@dataclass(frozen=True)
class SourceNodeRecord:
    source_kind: RoadSource
    source_node_id: str
    geometry: Point
    crs: str
    properties: Mapping[str, Any] | None = None

    def validate(self, expected_crs: str) -> None:
        if not self.source_node_id:
            raise MaterializationError("source Node identity is empty")
        if not isinstance(self.geometry, Point):
            raise MaterializationError("source Node must be a Point")
        if self.geometry.is_empty or not self.geometry.is_valid:
            raise MaterializationError("source Node geometry is empty or invalid")
        if _canonical_crs(self.crs) != _canonical_crs(expected_crs):
            raise MaterializationError("source Node CRS differs from the materializer CRS")


@dataclass(frozen=True)
class GeometrySlice:
    source_kind: RoadSource
    source_road_id: str
    start_position_m: float = 0.0
    end_position_m: float | None = None
    reverse_geometry: bool = False

    @property
    def source_key(self) -> tuple[RoadSource, str]:
        return self.source_kind, self.source_road_id


@dataclass(frozen=True)
class NodeRecipe:
    kind: NodeRecipeKind
    source_kind: RoadSource
    source_node_id: str = ""
    source_road_id: str = ""
    position_m: float | None = None
    output_node_id: str = ""

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "source_kind": self.source_kind.value,
            "source_node_id": self.source_node_id,
            "source_road_id": self.source_road_id,
            "position_m": self.position_m,
        }


@dataclass(frozen=True)
class RoadInstruction:
    instruction_id: str
    owner_segment_id: str
    role: RoadRole
    direction: int
    geometry_slices: tuple[GeometrySlice, ...]
    source_node_recipe: NodeRecipe
    target_node_recipe: NodeRecipe
    join_modes: tuple[GeometryJoinMode, ...] = ()
    output_road_id: str = ""
    source_endpoint_join_mode: GeometryJoinMode = (
        GeometryJoinMode.COINCIDENT_ONLY
    )
    target_endpoint_join_mode: GeometryJoinMode = (
        GeometryJoinMode.COINCIDENT_ONLY
    )


@dataclass(frozen=True)
class FrozenSegmentAccessContract:
    binding_id: str
    segment_id: str
    access_node_id: str
    structural_role: AccessStructuralRole
    direction_role: AccessDirectionRole


@dataclass(frozen=True)
class SegmentAccessBinding:
    binding_id: str
    segment_id: str
    access_node_id: str
    structural_role: AccessStructuralRole
    direction_role: AccessDirectionRole
    road_instruction_ids: tuple[str, ...]
    node_recipes: tuple[NodeRecipe, ...]


@dataclass(frozen=True)
class AttachmentInstruction:
    side: AttachmentEndpoint
    parent_access_binding_id: str
    child_road_instruction_id: str
    child_segment_id: str
    child_endpoint: AttachmentEndpoint
    target_kind: AttachmentTargetKind
    parent_road_instruction_id: str = ""
    parent_position_m: float | None = None
    target_node_id: str = ""


@dataclass(frozen=True)
class SegmentMaterializationInstruction:
    segment_id: str
    segment_type: SegmentMaterializationType
    decision: SegmentDecision
    roads: tuple[RoadInstruction, ...]
    access_bindings: tuple[SegmentAccessBinding, ...] = ()
    attachments: tuple[AttachmentInstruction, ...] = ()
    fallback_applied: bool = False


@dataclass(frozen=True)
class MaterializedNode:
    node_id: str
    geometry: Point
    source_kind: RoadSource
    source_reference_id: str
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class MaterializedRoad:
    road_id: str
    instruction_id: str
    owner_segment_id: str
    role: RoadRole
    direction: int
    source_node_id: str
    target_node_id: str
    geometry: LineString
    source_references: tuple[tuple[RoadSource, str], ...]
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class MaterializedSegmentAccessBinding:
    binding_id: str
    segment_id: str
    access_node_id: str
    structural_role: AccessStructuralRole
    direction_role: AccessDirectionRole
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class MaterializedAttachment:
    side: AttachmentEndpoint
    parent_access_binding_id: str
    child_road_id: str
    child_segment_id: str
    child_endpoint: AttachmentEndpoint
    target_kind: AttachmentTargetKind
    parent_road_id: str
    parent_position_m: float | None
    target_node_id: str


@dataclass(frozen=True)
class MaterializedRoadGraph:
    crs: str
    roads: tuple[MaterializedRoad, ...]
    nodes: tuple[MaterializedNode, ...]
    directed_edges: tuple[tuple[str, str], ...]
    access_bindings: Mapping[str, MaterializedSegmentAccessBinding]
    attachments: tuple[MaterializedAttachment, ...]
    positive_keep_segment_ids: tuple[str, ...]
    fallback_segment_ids: tuple[str, ...]
    skeleton_mutation_count: int
    silent_fix: bool
    content_repair: bool


def materialize_target_a_roadgraph(
    *,
    frozen_segment_ids: Sequence[str],
    frozen_access_contracts: Sequence[FrozenSegmentAccessContract],
    segment_instructions: Sequence[SegmentMaterializationInstruction],
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    expected_crs: str = "EPSG:3857",
    coordinate_tolerance_m: float = 0.05,
) -> MaterializedRoadGraph:
    """Execute declared ledger operations without making business choices."""
    if coordinate_tolerance_m < 0:
        raise MaterializationError("coordinate tolerance must not be negative")
    expected_segments = {str(value) for value in frozen_segment_ids}
    if len(expected_segments) != len(tuple(frozen_segment_ids)):
        raise MaterializationError("frozen Segment ids must be unique")
    instructions_by_segment = {
        row.segment_id: row for row in segment_instructions
    }
    if len(instructions_by_segment) != len(tuple(segment_instructions)):
        raise MaterializationError("Segment materialization instructions are duplicated")
    observed_segments = set(instructions_by_segment)
    if observed_segments != expected_segments:
        missing = sorted(expected_segments - observed_segments)
        extra = sorted(observed_segments - expected_segments)
        raise MaterializationError(
            f"materialization would mutate the frozen Segment skeleton: "
            f"missing={missing}, extra={extra}"
        )
    contracts_by_id = _index_frozen_access_contracts(
        frozen_access_contracts,
        expected_segments=expected_segments,
        instructions_by_segment=instructions_by_segment,
    )

    roads_by_instruction: dict[str, MaterializedRoad] = {}
    road_instruction_by_id: dict[str, RoadInstruction] = {}
    road_ids: set[str] = set()
    nodes_by_id: dict[str, MaterializedNode] = {}
    node_recipe_by_id: dict[str, NodeRecipe] = {}
    source_intervals: dict[
        tuple[RoadSource, str], list[tuple[float, float, str]]
    ] = {}
    for segment in sorted(segment_instructions, key=lambda row: row.segment_id):
        _validate_segment_instruction(segment)
        for instruction in segment.roads:
            if instruction.instruction_id in roads_by_instruction:
                if (
                    instruction.role is RoadRole.JUNCTION_CONNECTIVITY
                    and not instruction.owner_segment_id
                    and road_instruction_by_id[instruction.instruction_id]
                    == instruction
                ):
                    continue
                raise MaterializationError(
                    "owned Road instruction ids must be globally unique"
                )
            road = _materialize_road(
                instruction,
                source_roads=source_roads,
                source_nodes=source_nodes,
                expected_crs=expected_crs,
                coordinate_tolerance_m=coordinate_tolerance_m,
                nodes_by_id=nodes_by_id,
                node_recipe_by_id=node_recipe_by_id,
                source_intervals=source_intervals,
            )
            if road.road_id in road_ids:
                raise MaterializationError("final Road ids must be unique")
            road_ids.add(road.road_id)
            roads_by_instruction[instruction.instruction_id] = road
            road_instruction_by_id[instruction.instruction_id] = instruction

    owned_roads_by_segment: dict[
        str, list[tuple[str, MaterializedRoad]]
    ] = {}
    for instruction_id, road in roads_by_instruction.items():
        if road.owner_segment_id:
            owned_roads_by_segment.setdefault(
                road.owner_segment_id, []
            ).append((instruction_id, road))
    access_bindings: dict[str, MaterializedSegmentAccessBinding] = {}
    for segment in sorted(segment_instructions, key=lambda row: row.segment_id):
        if segment.segment_type is SegmentMaterializationType.STANDARD:
            for binding in segment.access_bindings:
                materialized = _materialize_access_binding(
                    binding,
                    segment=segment,
                    contract=contracts_by_id.get(binding.binding_id),
                    roads_by_instruction=roads_by_instruction,
                    owned_segment_roads=owned_roads_by_segment.get(
                        segment.segment_id, ()
                    ),
                    source_roads=source_roads,
                    source_nodes=source_nodes,
                    expected_crs=expected_crs,
                    coordinate_tolerance_m=coordinate_tolerance_m,
                    nodes_by_id=nodes_by_id,
                    node_recipe_by_id=node_recipe_by_id,
                )
                if materialized.binding_id in access_bindings:
                    raise MaterializationError(
                        "Segment access binding ids must be globally unique"
                    )
                access_bindings[materialized.binding_id] = materialized
            if segment.attachments:
                raise MaterializationError(
                    "ordinary Segment cannot declare AdvanceRight side attachments"
                )
        else:
            if segment.access_bindings:
                raise MaterializationError(
                    "AdvanceRight references ordinary access and cannot own a binding"
                )
            owned_ar = [
                road
                for road in roads_by_instruction.values()
                if road.owner_segment_id == segment.segment_id
                and road.role is RoadRole.ADVANCE_RIGHT
            ]
            if not owned_ar:
                raise MaterializationError(
                    "AdvanceRight lacks its independent owned Road"
                )
    if set(access_bindings) != set(contracts_by_id):
        missing = sorted(set(contracts_by_id) - set(access_bindings))
        extra = sorted(set(access_bindings) - set(contracts_by_id))
        raise MaterializationError(
            "materialized access bindings differ from the frozen relation set: "
            f"missing={missing}, extra={extra}"
        )

    materialized_attachments: list[MaterializedAttachment] = []
    for segment in sorted(segment_instructions, key=lambda row: row.segment_id):
        if segment.segment_type is not SegmentMaterializationType.ADVANCE_RIGHT:
            continue
        sides = [row.side for row in segment.attachments]
        if sorted(side.value for side in sides) != [
            AttachmentEndpoint.SOURCE.value,
            AttachmentEndpoint.TARGET.value,
        ]:
            raise MaterializationError(
                "AdvanceRight must declare exactly one SOURCE and one TARGET attachment"
            )
        for attachment in segment.attachments:
            materialized_attachments.append(
                _validate_attachment(
                    attachment,
                    segment=segment,
                    roads_by_instruction=roads_by_instruction,
                    access_bindings=access_bindings,
                    coordinate_tolerance_m=coordinate_tolerance_m,
                )
            )

    directed_edges: set[tuple[str, str]] = set()
    for road in roads_by_instruction.values():
        if (
            road.source_node_id not in nodes_by_id
            or road.target_node_id not in nodes_by_id
        ):
            raise MaterializationError("Road endpoint references an absent final Node")
        if road.direction in FORWARD_DIRECTIONS:
            directed_edges.add((road.source_node_id, road.target_node_id))
        if road.direction in REVERSE_DIRECTIONS:
            directed_edges.add((road.target_node_id, road.source_node_id))

    positive_keep = tuple(
        sorted(
            row.segment_id
            for row in segment_instructions
            if row.decision is SegmentDecision.KEEP_SWSD
            and not row.fallback_applied
        )
    )
    fallback = tuple(
        sorted(row.segment_id for row in segment_instructions if row.fallback_applied)
    )
    return MaterializedRoadGraph(
        crs=_canonical_crs(expected_crs),
        roads=tuple(
            roads_by_instruction[key] for key in sorted(roads_by_instruction)
        ),
        nodes=tuple(nodes_by_id[key] for key in sorted(nodes_by_id)),
        directed_edges=tuple(sorted(directed_edges)),
        access_bindings={
            key: access_bindings[key] for key in sorted(access_bindings)
        },
        attachments=tuple(
            sorted(
                materialized_attachments,
                key=lambda row: (
                    row.child_segment_id,
                    row.side.value,
                    row.child_road_id,
                ),
            )
        ),
        positive_keep_segment_ids=positive_keep,
        fallback_segment_ids=fallback,
        skeleton_mutation_count=0,
        silent_fix=False,
        content_repair=False,
    )


def _validate_segment_instruction(
    segment: SegmentMaterializationInstruction,
) -> None:
    if not segment.segment_id:
        raise MaterializationError("Segment materialization id is empty")
    if not segment.roads:
        raise MaterializationError(
            "materialization requires an effective complete Road plan"
        )
    local_ids = [row.instruction_id for row in segment.roads]
    if any(not value for value in local_ids) or len(local_ids) != len(set(local_ids)):
        raise MaterializationError("Segment Road instruction ids are empty or duplicated")
    for road in segment.roads:
        if road.role is RoadRole.JUNCTION_CONNECTIVITY:
            if road.owner_segment_id:
                raise MaterializationError(
                    "Junction connectivity Road must not have a Segment owner"
                )
        elif road.owner_segment_id != segment.segment_id:
            raise MaterializationError(
                "owned Road instruction differs from its Segment"
            )
    owned_sources = {
        geometry_slice.source_kind
        for road in segment.roads
        if road.owner_segment_id == segment.segment_id
        for geometry_slice in road.geometry_slices
    }
    if segment.fallback_applied and owned_sources != {RoadSource.SWSD}:
        raise MaterializationError("executed Segment fallback must be a full SWSD plan")
    if (
        segment.decision is SegmentDecision.KEEP_SWSD
        and not segment.fallback_applied
        and owned_sources != {RoadSource.SWSD}
    ):
        raise MaterializationError("positive KEEP must materialize only SWSD Roads")
    if (
        segment.decision is SegmentDecision.USE_RCSD
        and RoadSource.SWSD in owned_sources
    ):
        raise MaterializationError("USE_RCSD cannot materialize a SWSD main Road")


def _materialize_road(
    instruction: RoadInstruction,
    *,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    expected_crs: str,
    coordinate_tolerance_m: float,
    nodes_by_id: dict[str, MaterializedNode],
    node_recipe_by_id: dict[str, NodeRecipe],
    source_intervals: dict[
        tuple[RoadSource, str], list[tuple[float, float, str]]
    ],
) -> MaterializedRoad:
    if instruction.direction not in FORWARD_DIRECTIONS | REVERSE_DIRECTIONS:
        raise MaterializationError("final Road direction is outside the formal enum")
    if not instruction.geometry_slices:
        raise MaterializationError("Road instruction has no source geometry")
    if len(instruction.join_modes) != len(instruction.geometry_slices) - 1:
        raise MaterializationError("Road join recipe count differs from geometry parts")
    geometries: list[LineString] = []
    source_references: list[tuple[RoadSource, str]] = []
    first_properties: Mapping[str, Any] = {}
    for index, geometry_slice in enumerate(instruction.geometry_slices):
        source = source_roads.get(geometry_slice.source_key)
        if source is None:
            raise MaterializationError("Road instruction references an absent source Road")
        source.validate(expected_crs)
        if index == 0:
            first_properties = dict(source.properties or {})
        start, end = _validated_interval(geometry_slice, source)
        _register_source_interval(
            geometry_slice.source_key,
            start,
            end,
            instruction.instruction_id,
            source_intervals,
            coordinate_tolerance_m,
        )
        part = substring(source.geometry, start, end)
        if not isinstance(part, LineString) or part.is_empty or part.length <= 0:
            raise MaterializationError("Road slice did not produce a nonempty LineString")
        if geometry_slice.reverse_geometry:
            part = LineString(list(part.coords)[::-1])
        geometries.append(part)
        source_references.append(geometry_slice.source_key)
    geometry = _join_geometry_parts(
        geometries,
        instruction.join_modes,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    source_node = _materialize_node(
        instruction.source_node_recipe,
        source_roads=source_roads,
        source_nodes=source_nodes,
        expected_crs=expected_crs,
    )
    target_node = _materialize_node(
        instruction.target_node_recipe,
        source_roads=source_roads,
        source_nodes=source_nodes,
        expected_crs=expected_crs,
    )
    _register_node(
        source_node,
        instruction.source_node_recipe,
        nodes_by_id=nodes_by_id,
        node_recipe_by_id=node_recipe_by_id,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    _register_node(
        target_node,
        instruction.target_node_recipe,
        nodes_by_id=nodes_by_id,
        node_recipe_by_id=node_recipe_by_id,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    geometry = _join_declared_endpoint(
        geometry,
        source_node.geometry,
        mode=instruction.source_endpoint_join_mode,
        at_source=True,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    geometry = _join_declared_endpoint(
        geometry,
        target_node.geometry,
        mode=instruction.target_endpoint_join_mode,
        at_source=False,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    output_id = instruction.output_road_id or _stable_numeric_id(
        "road",
        {
            "instruction_id": instruction.instruction_id,
            "owner_segment_id": instruction.owner_segment_id,
            "role": instruction.role.value,
            "direction": instruction.direction,
            "geometry_slices": [
                {
                    "source_kind": row.source_kind.value,
                    "source_road_id": row.source_road_id,
                    "start_position_m": row.start_position_m,
                    "end_position_m": row.end_position_m,
                    "reverse_geometry": row.reverse_geometry,
                }
                for row in instruction.geometry_slices
            ],
            "join_modes": [row.value for row in instruction.join_modes],
            "source_endpoint_join_mode": (
                instruction.source_endpoint_join_mode.value
            ),
            "target_endpoint_join_mode": (
                instruction.target_endpoint_join_mode.value
            ),
        },
    )
    properties = dict(first_properties)
    properties.update(
        {
            "id": output_id,
            "snodeid": source_node.node_id,
            "enodeid": target_node.node_id,
            "direction": instruction.direction,
            "owner_segment_id": instruction.owner_segment_id,
            "road_role": instruction.role.value,
        }
    )
    return MaterializedRoad(
        road_id=output_id,
        instruction_id=instruction.instruction_id,
        owner_segment_id=instruction.owner_segment_id,
        role=instruction.role,
        direction=instruction.direction,
        source_node_id=source_node.node_id,
        target_node_id=target_node.node_id,
        geometry=geometry,
        source_references=tuple(source_references),
        properties=properties,
    )


def _join_declared_endpoint(
    geometry: LineString,
    node: Point,
    *,
    mode: GeometryJoinMode,
    at_source: bool,
    coordinate_tolerance_m: float,
) -> LineString:
    coordinates = list(geometry.coords)
    endpoint = Point(coordinates[0] if at_source else coordinates[-1])
    if endpoint.distance(node) <= coordinate_tolerance_m:
        return geometry
    if mode is not GeometryJoinMode.STRAIGHT_CONNECTOR:
        endpoint_name = "source" if at_source else "target"
        raise MaterializationError(
            f"declared {endpoint_name} Node does not match Road geometry"
        )
    node_coordinate = (float(node.x), float(node.y))
    joined = LineString(
        [node_coordinate, *coordinates]
        if at_source
        else [*coordinates, node_coordinate]
    )
    if joined.is_empty or not joined.is_valid or joined.length <= 0:
        raise MaterializationError(
            "declared endpoint connector produced invalid Road geometry"
        )
    return joined


def _validated_interval(
    geometry_slice: GeometrySlice,
    source: SourceRoadRecord,
) -> tuple[float, float]:
    start = float(geometry_slice.start_position_m)
    end = (
        float(source.geometry.length)
        if geometry_slice.end_position_m is None
        else float(geometry_slice.end_position_m)
    )
    length = float(source.geometry.length)
    if start < 0 or end > length or end <= start:
        raise MaterializationError("Road slice interval is outside its source Road")
    return start, end


def _register_source_interval(
    source_key: tuple[RoadSource, str],
    start: float,
    end: float,
    instruction_id: str,
    intervals: dict[tuple[RoadSource, str], list[tuple[float, float, str]]],
    tolerance_m: float,
) -> None:
    for existing_start, existing_end, existing_id in intervals.get(source_key, ()):
        overlap = min(end, existing_end) - max(start, existing_start)
        if existing_id != instruction_id and overlap > tolerance_m:
            raise MaterializationError(
                "final owned Road pieces overlap on the same source Road"
            )
    intervals.setdefault(source_key, []).append((start, end, instruction_id))


def _join_geometry_parts(
    parts: Sequence[LineString],
    join_modes: Sequence[GeometryJoinMode],
    *,
    coordinate_tolerance_m: float,
) -> LineString:
    coordinates = list(parts[0].coords)
    for mode, part in zip(join_modes, parts[1:], strict=True):
        following = list(part.coords)
        gap = Point(coordinates[-1]).distance(Point(following[0]))
        if mode is GeometryJoinMode.COINCIDENT_ONLY:
            if gap > coordinate_tolerance_m:
                raise MaterializationError(
                    "COINCIDENT_ONLY geometry parts have a nonzero gap"
                )
            coordinates.extend(following[1:])
        elif mode is GeometryJoinMode.STRAIGHT_CONNECTOR:
            if gap <= coordinate_tolerance_m:
                coordinates.extend(following[1:])
            else:
                coordinates.extend(following)
        else:
            raise MaterializationError("unsupported geometry join mode")
    geometry = LineString(coordinates)
    if geometry.is_empty or not geometry.is_valid or geometry.length <= 0:
        raise MaterializationError("materialized Road geometry is invalid")
    return geometry


def _materialize_node(
    recipe: NodeRecipe,
    *,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    expected_crs: str,
) -> MaterializedNode:
    if recipe.kind is NodeRecipeKind.COPY_SOURCE_NODE:
        if not recipe.source_node_id or recipe.source_road_id or recipe.position_m is not None:
            raise MaterializationError("COPY_SOURCE_NODE recipe fields are invalid")
        source = source_nodes.get((recipe.source_kind, recipe.source_node_id))
        if source is None:
            raise MaterializationError("Node recipe references an absent source Node")
        source.validate(expected_crs)
        point = source.geometry
        reference_id = source.source_node_id
        properties = dict(source.properties or {})
    elif recipe.kind is NodeRecipeKind.INTERPOLATE_SOURCE_ROAD:
        if (
            not recipe.source_road_id
            or recipe.source_node_id
            or recipe.position_m is None
        ):
            raise MaterializationError(
                "INTERPOLATE_SOURCE_ROAD recipe fields are invalid"
            )
        source_road = source_roads.get(
            (recipe.source_kind, recipe.source_road_id)
        )
        if source_road is None:
            raise MaterializationError("Node recipe references an absent source Road")
        source_road.validate(expected_crs)
        position = float(recipe.position_m)
        if position < 0 or position > source_road.geometry.length:
            raise MaterializationError("Node interpolation position is outside Road")
        point = source_road.geometry.interpolate(position)
        reference_id = source_road.source_road_id
        properties = {}
    else:
        raise MaterializationError("unsupported Node recipe")
    node_id = recipe.output_node_id or _stable_numeric_id(
        "node", recipe.semantic_payload()
    )
    properties.update({"id": node_id})
    return MaterializedNode(
        node_id=node_id,
        geometry=point,
        source_kind=recipe.source_kind,
        source_reference_id=reference_id,
        properties=properties,
    )


def _register_node(
    node: MaterializedNode,
    recipe: NodeRecipe,
    *,
    nodes_by_id: dict[str, MaterializedNode],
    node_recipe_by_id: dict[str, NodeRecipe],
    coordinate_tolerance_m: float,
) -> None:
    existing = nodes_by_id.get(node.node_id)
    if existing is None:
        nodes_by_id[node.node_id] = node
        node_recipe_by_id[node.node_id] = recipe
        return
    if (
        node_recipe_by_id[node.node_id].semantic_payload()
        != recipe.semantic_payload()
        or existing.geometry.distance(node.geometry) > coordinate_tolerance_m
    ):
        raise MaterializationError("final Node id has conflicting recipes")


def _index_frozen_access_contracts(
    contracts: Sequence[FrozenSegmentAccessContract],
    *,
    expected_segments: set[str],
    instructions_by_segment: Mapping[str, SegmentMaterializationInstruction],
) -> dict[str, FrozenSegmentAccessContract]:
    contracts_by_id = {row.binding_id: row for row in contracts}
    if len(contracts_by_id) != len(tuple(contracts)):
        raise MaterializationError("frozen access contract ids must be unique")
    relation_keys: set[tuple[str, str]] = set()
    endpoint_counts: Counter[str] = Counter()
    for contract in contracts:
        if (
            not contract.binding_id
            or not contract.segment_id
            or not contract.access_node_id
        ):
            raise MaterializationError("frozen access contract identity is incomplete")
        if contract.segment_id not in expected_segments:
            raise MaterializationError(
                "frozen access contract references an absent Segment"
            )
        if (
            instructions_by_segment[contract.segment_id].segment_type
            is not SegmentMaterializationType.STANDARD
        ):
            raise MaterializationError(
                "only ordinary Segments own frozen access bindings"
            )
        relation_key = (contract.segment_id, contract.access_node_id)
        if relation_key in relation_keys:
            raise MaterializationError(
                "frozen Segment access relation is duplicated"
            )
        relation_keys.add(relation_key)
        if contract.structural_role is AccessStructuralRole.ENDPOINT:
            endpoint_counts[contract.segment_id] += 1
    for segment_id, instruction in instructions_by_segment.items():
        if (
            instruction.segment_type is SegmentMaterializationType.STANDARD
            and endpoint_counts[segment_id] != 2
        ):
            raise MaterializationError(
                "ordinary Segment must retain exactly two frozen endpoint access relations"
            )
    return contracts_by_id


def _materialize_access_binding(
    binding: SegmentAccessBinding,
    *,
    segment: SegmentMaterializationInstruction,
    contract: FrozenSegmentAccessContract | None,
    roads_by_instruction: Mapping[str, MaterializedRoad],
    owned_segment_roads: Sequence[tuple[str, MaterializedRoad]],
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    expected_crs: str,
    coordinate_tolerance_m: float,
    nodes_by_id: dict[str, MaterializedNode],
    node_recipe_by_id: dict[str, NodeRecipe],
) -> MaterializedSegmentAccessBinding:
    if contract is None:
        raise MaterializationError(
            "model access binding has no frozen Junction-Segment relation"
        )
    if (
        binding.segment_id != segment.segment_id
        or binding.segment_id != contract.segment_id
        or binding.access_node_id != contract.access_node_id
        or binding.structural_role is not contract.structural_role
        or binding.direction_role is not contract.direction_role
    ):
        raise MaterializationError(
            "model access binding changes its frozen relation or business roles"
        )
    if not binding.road_instruction_ids or not binding.node_recipes:
        raise MaterializationError(
            "ordinary access must output a nonempty complete Road/Node set"
        )
    if (
        len(set(binding.road_instruction_ids))
        != len(binding.road_instruction_ids)
    ):
        raise MaterializationError("access Road instruction ids are duplicated")

    bound_roads: list[MaterializedRoad] = []
    owned_road_count = 0
    for instruction_id in binding.road_instruction_ids:
        road = roads_by_instruction.get(instruction_id)
        if road is None:
            raise MaterializationError(
                "access binding references an absent final Road"
            )
        if road.owner_segment_id == binding.segment_id:
            owned_road_count += 1
        elif not (
            road.role is RoadRole.JUNCTION_CONNECTIVITY
            and not road.owner_segment_id
        ):
            raise MaterializationError(
                "ordinary access cannot acquire another Segment's Road"
            )
        bound_roads.append(road)
    if owned_road_count == 0:
        raise MaterializationError(
            "ordinary access must include at least one owned carrier Road"
        )

    bound_nodes: list[MaterializedNode] = []
    for recipe in binding.node_recipes:
        node = _materialize_node(
            recipe,
            source_roads=source_roads,
            source_nodes=source_nodes,
            expected_crs=expected_crs,
        )
        _register_node(
            node,
            recipe,
            nodes_by_id=nodes_by_id,
            node_recipe_by_id=node_recipe_by_id,
            coordinate_tolerance_m=coordinate_tolerance_m,
        )
        bound_nodes.append(node)
    node_ids = [row.node_id for row in bound_nodes]
    if len(set(node_ids)) != len(node_ids):
        raise MaterializationError("access Node recipes resolve to duplicate final Nodes")

    declared_instruction_ids = set(binding.road_instruction_ids)
    actual_roles: set[AccessDirectionRole] = set()
    for road in bound_roads:
        source_match, target_match = _road_access_incidence(
            road,
            bound_nodes,
            coordinate_tolerance_m=coordinate_tolerance_m,
        )
        if not source_match and not target_match:
            raise MaterializationError(
                "access Road does not meet any declared access Node"
            )
        actual_roles.update(
            _incidence_direction_roles(
                road.direction,
                source_match=source_match,
                target_match=target_match,
            )
        )
    for instruction_id, road in owned_segment_roads:
        if instruction_id in declared_instruction_ids:
            continue
        source_match, target_match = _road_access_incidence(
            road,
            bound_nodes,
            coordinate_tolerance_m=coordinate_tolerance_m,
        )
        if source_match or target_match:
            raise MaterializationError(
                "ordinary access Road set omits an owned Road meeting that access"
            )
    observed_direction = _combined_direction_role(actual_roles)
    if (
        binding.direction_role is not AccessDirectionRole.UNKNOWN
        and binding.direction_role is not observed_direction
    ):
        raise MaterializationError(
            "access direction role differs from its complete Road/Node set"
        )
    return MaterializedSegmentAccessBinding(
        binding_id=binding.binding_id,
        segment_id=binding.segment_id,
        access_node_id=binding.access_node_id,
        structural_role=binding.structural_role,
        direction_role=binding.direction_role,
        road_ids=tuple(row.road_id for row in bound_roads),
        node_ids=tuple(node_ids),
    )


def _road_access_incidence(
    road: MaterializedRoad,
    nodes: Sequence[MaterializedNode],
    *,
    coordinate_tolerance_m: float,
) -> tuple[bool, bool]:
    source_point = Point(road.geometry.coords[0])
    target_point = Point(road.geometry.coords[-1])
    return (
        any(
            source_point.distance(node.geometry) <= coordinate_tolerance_m
            for node in nodes
        ),
        any(
            target_point.distance(node.geometry) <= coordinate_tolerance_m
            for node in nodes
        ),
    )


def _incidence_direction_roles(
    direction: int,
    *,
    source_match: bool,
    target_match: bool,
) -> set[AccessDirectionRole]:
    roles: set[AccessDirectionRole] = set()
    if direction in FORWARD_DIRECTIONS:
        if source_match:
            roles.add(AccessDirectionRole.EXIT)
        if target_match:
            roles.add(AccessDirectionRole.ENTER)
    if direction in REVERSE_DIRECTIONS:
        if source_match:
            roles.add(AccessDirectionRole.ENTER)
        if target_match:
            roles.add(AccessDirectionRole.EXIT)
    return roles


def _combined_direction_role(
    roles: set[AccessDirectionRole],
) -> AccessDirectionRole:
    if roles == {AccessDirectionRole.ENTER}:
        return AccessDirectionRole.ENTER
    if roles == {AccessDirectionRole.EXIT}:
        return AccessDirectionRole.EXIT
    if roles == {AccessDirectionRole.ENTER, AccessDirectionRole.EXIT}:
        return AccessDirectionRole.BOTH
    raise MaterializationError("access Road/Node set has no directed incidence")


def _validate_attachment(
    attachment: AttachmentInstruction,
    *,
    segment: SegmentMaterializationInstruction,
    roads_by_instruction: Mapping[str, MaterializedRoad],
    access_bindings: Mapping[str, MaterializedSegmentAccessBinding],
    coordinate_tolerance_m: float,
) -> MaterializedAttachment:
    if attachment.child_segment_id != segment.segment_id:
        raise MaterializationError("attachment child Segment differs from its plan")
    binding = access_bindings.get(attachment.parent_access_binding_id)
    if binding is None:
        raise MaterializationError(
            "AdvanceRight attachment references an absent ordinary access binding"
        )
    if binding.segment_id == attachment.child_segment_id:
        raise MaterializationError(
            "AdvanceRight cannot own its parent access binding"
        )
    child = roads_by_instruction.get(attachment.child_road_instruction_id)
    if child is None:
        raise MaterializationError("attachment references an absent child Road")
    if child.owner_segment_id != attachment.child_segment_id:
        raise MaterializationError("attachment child Road ownership differs")
    child_node_id = (
        child.source_node_id
        if attachment.child_endpoint is AttachmentEndpoint.SOURCE
        else child.target_node_id
    )
    child_point = Point(
        child.geometry.coords[0]
        if attachment.child_endpoint is AttachmentEndpoint.SOURCE
        else child.geometry.coords[-1]
    )
    parent_road_id = ""
    parent_position_m: float | None = None
    target_node_id = ""
    if attachment.target_kind is AttachmentTargetKind.ROAD_POSITION:
        if (
            not attachment.parent_road_instruction_id
            or attachment.parent_position_m is None
            or attachment.target_node_id
        ):
            raise MaterializationError(
                "RCSD Road-position attachment fields are incomplete"
            )
        parent = roads_by_instruction.get(attachment.parent_road_instruction_id)
        if parent is None or parent.road_id not in binding.road_ids:
            raise MaterializationError(
                "RCSD parent Road is not part of the selected access binding"
            )
        position = float(attachment.parent_position_m)
        if position < 0 or position > parent.geometry.length:
            raise MaterializationError("attachment position is outside parent Road")
        parent_point = parent.geometry.interpolate(position)
        at_source = position <= coordinate_tolerance_m
        at_target = (
            parent.geometry.length - position <= coordinate_tolerance_m
        )
        if not at_source and not at_target:
            raise MaterializationError(
                "RCSD parent Road must be explicitly split at the attachment"
            )
        parent_node_id = (
            parent.source_node_id if at_source else parent.target_node_id
        )
        if (
            parent_point.distance(child_point) > coordinate_tolerance_m
            or parent_node_id != child_node_id
        ):
            raise MaterializationError(
                "declared RCSD Road-position attachment does not share its final Node"
            )
        parent_road_id = parent.road_id
        parent_position_m = position
    elif attachment.target_kind is AttachmentTargetKind.FROZEN_ACCESS_NODE:
        if (
            attachment.parent_road_instruction_id
            or attachment.parent_position_m is not None
            or not attachment.target_node_id
        ):
            raise MaterializationError(
                "frozen Node/JunctionUnit attachment fields are incomplete"
            )
        if attachment.target_node_id not in binding.node_ids:
            raise MaterializationError(
                "frozen attachment Node is outside the selected access binding"
            )
        if child_node_id != attachment.target_node_id:
            raise MaterializationError(
                "frozen attachment must reuse the exact final access Node"
            )
        target_node_id = attachment.target_node_id
    else:
        raise MaterializationError("unsupported attachment target kind")
    return MaterializedAttachment(
        side=attachment.side,
        parent_access_binding_id=attachment.parent_access_binding_id,
        child_road_id=child.road_id,
        child_segment_id=attachment.child_segment_id,
        child_endpoint=attachment.child_endpoint,
        target_kind=attachment.target_kind,
        parent_road_id=parent_road_id,
        parent_position_m=parent_position_m,
        target_node_id=target_node_id,
    )


def _stable_numeric_id(kind: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return str(8_000_000_000_000_000_000 + int(digest[:15], 16) % 10**18)


@lru_cache(maxsize=32)
def _canonical_crs(value: str) -> str:
    crs = CRS.from_user_input(value)
    authority = crs.to_authority()
    return (
        f"{authority[0]}:{authority[1]}"
        if authority
        else crs.to_wkt()
    )


__all__ = [
    "AccessDirectionRole",
    "AccessStructuralRole",
    "AttachmentEndpoint",
    "AttachmentInstruction",
    "AttachmentTargetKind",
    "FrozenSegmentAccessContract",
    "GeometryJoinMode",
    "GeometrySlice",
    "MaterializationError",
    "MaterializedAttachment",
    "MaterializedNode",
    "MaterializedRoad",
    "MaterializedRoadGraph",
    "MaterializedSegmentAccessBinding",
    "NodeRecipe",
    "NodeRecipeKind",
    "RoadInstruction",
    "SegmentAccessBinding",
    "SegmentMaterializationInstruction",
    "SegmentMaterializationType",
    "SourceNodeRecord",
    "SourceRoadRecord",
    "materialize_target_a_roadgraph",
]
