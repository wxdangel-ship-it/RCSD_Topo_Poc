from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from pyproj import CRS
from shapely import unary_union
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorResult,
    AnchorState,
    CandidateBinding,
    JunctionPredictionError,
    JunctionResultPrediction,
    QualityState,
    SurfaceMode,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


class JunctionMaterializationError(ValueError):
    """A selected plan cannot be executed without changing its business meaning."""


@dataclass(frozen=True)
class GeometryAsset:
    object_ref: ObjectRef
    crs: str
    geometry: BaseGeometry


@dataclass(frozen=True)
class GeneratedRoadFragment:
    generated_id: str
    source_road_ref: ObjectRef
    start_fraction: float
    end_fraction: float
    geometry: LineString


@dataclass(frozen=True)
class GeneratedBreakNode:
    generated_id: str
    source_road_ref: ObjectRef
    fraction: float
    geometry: Point


@dataclass(frozen=True)
class MaterializationLedger:
    junction_key: str
    selected_plan_id: str | None
    selected_object_keys: tuple[str, ...]
    executed_operations: tuple[str, ...]
    generated_ids: tuple[str, ...]
    planned_topology_signature: str | None
    actual_topology_signature: str | None
    topology_valid: bool
    fallback_scope: str | None
    failure_reason: str
    silent_fix_count: int


@dataclass(frozen=True)
class MaterializedJunctionResult:
    junction_key: str
    surface_geometry: Polygon | MultiPolygon | None
    associated_node_refs: tuple[ObjectRef, ...]
    associated_road_refs: tuple[ObjectRef, ...]
    generated_road_fragments: tuple[GeneratedRoadFragment, ...]
    generated_break_nodes: tuple[GeneratedBreakNode, ...]
    node_equivalence_keys: tuple[tuple[str, ...], ...]
    topology_signature: str | None
    fallback: bool
    ledger: MaterializationLedger


def business_topology_signature(anchor: AnchorResult) -> str:
    """Canonical signature of model-selected topology, independent of generated IDs."""

    anchor.validate()
    payload = {
        "state": anchor.state.value,
        "nodes": sorted(ref.key for ref in anchor.associated_rcsd_node_refs),
        "roads": sorted(ref.key for ref in anchor.associated_rcsd_road_refs),
        "main": anchor.selected_main_anchor.key if anchor.selected_main_anchor else None,
        "equivalence": sorted(
            sorted(ref.key for ref in group.node_refs)
            for group in anchor.node_equivalence_classes
        ),
        "breaks": sorted(
            ({
                "road": operation.road_ref.key,
                "fractions": [float(value) for value in operation.fractions],
            } for operation in anchor.road_break_operations),
            key=lambda item: item["road"],
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "junction-topology-v1:" + hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = "|".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()[:24]}"


class SelectedPlanMaterializer:
    """Executes geometry for one selected plan without making another selection."""

    VIRTUAL_RECIPE = "ASSOCIATED_OBJECT_BUFFER_HULL"

    def __init__(
        self,
        *,
        expected_crs: str = "EPSG:3857",
        connectivity_tolerance_m: float = 0.05,
    ) -> None:
        self.expected_crs = CRS.from_user_input(expected_crs)
        if connectivity_tolerance_m < 0.0:
            raise ValueError("connectivity_tolerance_m must be non-negative")
        self.connectivity_tolerance_m = float(connectivity_tolerance_m)

    def _failure(
        self,
        prediction: JunctionResultPrediction,
        reason: str,
        *,
        selected_refs: Sequence[ObjectRef] = (),
        operations: Sequence[str] = (),
    ) -> MaterializedJunctionResult:
        ledger = MaterializationLedger(
            junction_key=prediction.junction_key,
            selected_plan_id=prediction.selected_plan_id,
            selected_object_keys=tuple(sorted(ref.key for ref in selected_refs)),
            executed_operations=tuple(operations),
            generated_ids=(),
            planned_topology_signature=(
                prediction.post_materialization_topology_signature
            ),
            actual_topology_signature=None,
            topology_valid=False,
            fallback_scope="JUNCTION",
            failure_reason=reason,
            silent_fix_count=0,
        )
        return MaterializedJunctionResult(
            junction_key=prediction.junction_key,
            surface_geometry=None,
            associated_node_refs=(),
            associated_road_refs=(),
            generated_road_fragments=(),
            generated_break_nodes=(),
            node_equivalence_keys=(),
            topology_signature=None,
            fallback=True,
            ledger=ledger,
        )

    def _asset(
        self,
        ref: ObjectRef,
        geometry_assets: Mapping[ObjectRef, GeometryAsset],
    ) -> GeometryAsset:
        asset = geometry_assets.get(ref)
        if asset is None:
            raise JunctionMaterializationError(f"MISSING_GEOMETRY:{ref.key}")
        if asset.object_ref != ref:
            raise JunctionMaterializationError(f"GEOMETRY_IDENTITY_MISMATCH:{ref.key}")
        try:
            asset_crs = CRS.from_user_input(asset.crs)
        except Exception as exc:
            raise JunctionMaterializationError(f"INVALID_CRS:{ref.key}") from exc
        if not asset_crs.equals(self.expected_crs):
            raise JunctionMaterializationError(f"CRS_MISMATCH:{ref.key}")
        geometry = asset.geometry
        if geometry is None or geometry.is_empty or not geometry.is_valid:
            raise JunctionMaterializationError(f"INVALID_GEOMETRY:{ref.key}")
        return asset

    def _selected_assets(
        self,
        prediction: JunctionResultPrediction,
        geometry_assets: Mapping[ObjectRef, GeometryAsset],
    ) -> dict[ObjectRef, GeometryAsset]:
        refs = set(prediction.surface_plan.selected_rcsdintersection_refs)
        refs.update(prediction.anchor_result.associated_rcsd_node_refs)
        refs.update(prediction.anchor_result.associated_rcsd_road_refs)
        return {ref: self._asset(ref, geometry_assets) for ref in refs}

    @staticmethod
    def _validate_role_geometry(ref: ObjectRef, geometry: BaseGeometry) -> None:
        if ref.role == EvidenceRole.RCSD_INTERSECTION and not isinstance(
            geometry, (Polygon, MultiPolygon)
        ):
            raise JunctionMaterializationError(f"SURFACE_GEOMETRY_TYPE:{ref.key}")
        if ref.role == EvidenceRole.RCSD_NODE and not isinstance(geometry, Point):
            raise JunctionMaterializationError(f"NODE_GEOMETRY_TYPE:{ref.key}")
        if ref.role == EvidenceRole.RCSD_ROAD and not isinstance(geometry, LineString):
            raise JunctionMaterializationError(f"ROAD_GEOMETRY_TYPE:{ref.key}")

    def _surface(
        self,
        prediction: JunctionResultPrediction,
        assets: Mapping[ObjectRef, GeometryAsset],
        operations: list[str],
    ) -> Polygon | MultiPolygon:
        plan = prediction.surface_plan
        if plan.mode == SurfaceMode.EXISTING_RCSD_INTERSECTION:
            geometries = [assets[ref].geometry for ref in plan.selected_rcsdintersection_refs]
            surface = unary_union(geometries)
            operations.append("UNION_SELECTED_RCSD_INTERSECTIONS")
        elif plan.mode == SurfaceMode.VIRTUAL_SURFACE:
            recipe = plan.virtual_surface_recipe
            if recipe is None or recipe.recipe_type != self.VIRTUAL_RECIPE:
                raise JunctionMaterializationError("UNSUPPORTED_VIRTUAL_SURFACE_RECIPE")
            parameters = dict(recipe.parameters)
            if set(parameters) != {"buffer_m"} or parameters["buffer_m"] <= 0.0:
                raise JunctionMaterializationError("INVALID_VIRTUAL_SURFACE_PARAMETERS")
            member_refs = (
                prediction.anchor_result.associated_rcsd_node_refs
                + prediction.anchor_result.associated_rcsd_road_refs
            )
            if not member_refs:
                raise JunctionMaterializationError("VIRTUAL_SURFACE_HAS_NO_SELECTED_MEMBER")
            surface = unary_union([assets[ref].geometry for ref in member_refs]).buffer(
                parameters["buffer_m"]
            ).convex_hull
            operations.append(
                f"{self.VIRTUAL_RECIPE}:buffer_m={parameters['buffer_m']}"
            )
        else:
            raise JunctionMaterializationError(
                f"NON_MATERIALIZABLE_SURFACE_MODE:{plan.mode.value}"
            )
        if (
            surface.is_empty
            or not surface.is_valid
            or not isinstance(surface, (Polygon, MultiPolygon))
        ):
            raise JunctionMaterializationError("MATERIALIZED_SURFACE_INVALID")
        return surface

    def _topology_connected(
        self,
        anchor: AnchorResult,
        assets: Mapping[ObjectRef, GeometryAsset],
    ) -> bool:
        refs = anchor.associated_rcsd_node_refs + anchor.associated_rcsd_road_refs
        if len(refs) <= 1:
            return True
        neighbors: dict[ObjectRef, set[ObjectRef]] = {ref: set() for ref in refs}
        for left_index, left in enumerate(refs):
            for right in refs[left_index + 1 :]:
                if (
                    assets[left].geometry.distance(assets[right].geometry)
                    <= self.connectivity_tolerance_m
                ):
                    neighbors[left].add(right)
                    neighbors[right].add(left)
        for group in anchor.node_equivalence_classes:
            for left_index, left in enumerate(group.node_refs):
                for right in group.node_refs[left_index + 1 :]:
                    neighbors[left].add(right)
                    neighbors[right].add(left)
        visited = {refs[0]}
        frontier = [refs[0]]
        while frontier:
            current = frontier.pop()
            for neighbor in neighbors[current] - visited:
                visited.add(neighbor)
                frontier.append(neighbor)
        return len(visited) == len(refs)

    def _break_roads(
        self,
        prediction: JunctionResultPrediction,
        assets: Mapping[ObjectRef, GeometryAsset],
        operations: list[str],
    ) -> tuple[tuple[GeneratedRoadFragment, ...], tuple[GeneratedBreakNode, ...]]:
        fragments: list[GeneratedRoadFragment] = []
        nodes: list[GeneratedBreakNode] = []
        for operation in prediction.anchor_result.road_break_operations:
            line = assets[operation.road_ref].geometry
            if not isinstance(line, LineString) or line.length <= 0.0:
                raise JunctionMaterializationError(
                    f"ROAD_BREAK_GEOMETRY_INVALID:{operation.road_ref.key}"
                )
            boundaries = (0.0,) + operation.fractions + (1.0,)
            for start, end in zip(boundaries, boundaries[1:]):
                geometry = substring(line, start, end, normalized=True)
                if not isinstance(geometry, LineString) or geometry.is_empty:
                    raise JunctionMaterializationError(
                        f"ROAD_BREAK_FRAGMENT_INVALID:{operation.road_ref.key}"
                    )
                generated_id = _stable_id(
                    "road-fragment",
                    prediction.junction_key,
                    operation.road_ref.key,
                    f"{start:.12g}",
                    f"{end:.12g}",
                )
                fragments.append(
                    GeneratedRoadFragment(
                        generated_id=generated_id,
                        source_road_ref=operation.road_ref,
                        start_fraction=start,
                        end_fraction=end,
                        geometry=geometry,
                    )
                )
            for fraction in operation.fractions:
                generated_id = _stable_id(
                    "break-node",
                    prediction.junction_key,
                    operation.road_ref.key,
                    f"{fraction:.12g}",
                )
                nodes.append(
                    GeneratedBreakNode(
                        generated_id=generated_id,
                        source_road_ref=operation.road_ref,
                        fraction=fraction,
                        geometry=line.interpolate(fraction, normalized=True),
                    )
                )
            operations.append(
                "BREAK_SELECTED_ROAD:"
                + operation.road_ref.key
                + ":"
                + ",".join(f"{value:.12g}" for value in operation.fractions)
            )
        return tuple(fragments), tuple(nodes)

    def materialize(
        self,
        *,
        prediction: JunctionResultPrediction,
        binding: CandidateBinding,
        geometry_assets: Mapping[ObjectRef, GeometryAsset],
    ) -> MaterializedJunctionResult:
        selected_refs: tuple[ObjectRef, ...] = ()
        operations: list[str] = []
        try:
            prediction.validate(binding)
            if prediction.abstain:
                return self._failure(prediction, "MODEL_ABSTAIN")
            if (
                prediction.anchor_result.state != AnchorState.SUCCESS
                or prediction.quality_state != QualityState.NORMAL
            ):
                return self._failure(prediction, "MODEL_REQUESTED_JUNCTION_FALLBACK")
            selected_refs = tuple(
                sorted(
                    binding.plan(prediction.selected_plan_id or "").referenced_objects,
                    key=lambda ref: ref.key,
                )
            )
            assets = self._selected_assets(prediction, geometry_assets)
            for ref, asset in assets.items():
                self._validate_role_geometry(ref, asset.geometry)
            surface = self._surface(prediction, assets, operations)
            for ref in (
                prediction.anchor_result.associated_rcsd_node_refs
                + prediction.anchor_result.associated_rcsd_road_refs
            ):
                if surface.distance(assets[ref].geometry) > self.connectivity_tolerance_m:
                    raise JunctionMaterializationError(
                        f"SELECTED_SURFACE_MEMBER_DISJOINT:{ref.key}"
                    )
            if not self._topology_connected(prediction.anchor_result, assets):
                raise JunctionMaterializationError("SELECTED_TOPOLOGY_DISCONNECTED")
            fragments, break_nodes = self._break_roads(
                prediction,
                assets,
                operations,
            )
            actual_signature = business_topology_signature(prediction.anchor_result)
            if actual_signature != prediction.post_materialization_topology_signature:
                raise JunctionMaterializationError("TOPOLOGY_SIGNATURE_MISMATCH")
            generated_ids = tuple(
                item.generated_id for item in fragments + break_nodes
            )
            ledger = MaterializationLedger(
                junction_key=prediction.junction_key,
                selected_plan_id=prediction.selected_plan_id,
                selected_object_keys=tuple(sorted(ref.key for ref in selected_refs)),
                executed_operations=tuple(operations),
                generated_ids=generated_ids,
                planned_topology_signature=prediction.post_materialization_topology_signature,
                actual_topology_signature=actual_signature,
                topology_valid=True,
                fallback_scope=None,
                failure_reason="",
                silent_fix_count=0,
            )
            return MaterializedJunctionResult(
                junction_key=prediction.junction_key,
                surface_geometry=surface,
                associated_node_refs=prediction.anchor_result.associated_rcsd_node_refs,
                associated_road_refs=prediction.anchor_result.associated_rcsd_road_refs,
                generated_road_fragments=fragments,
                generated_break_nodes=break_nodes,
                node_equivalence_keys=tuple(
                    tuple(ref.key for ref in group.node_refs)
                    for group in prediction.anchor_result.node_equivalence_classes
                ),
                topology_signature=actual_signature,
                fallback=False,
                ledger=ledger,
            )
        except (JunctionMaterializationError, JunctionPredictionError) as exc:
            return self._failure(
                prediction,
                str(exc),
                selected_refs=selected_refs,
                operations=operations,
            )
