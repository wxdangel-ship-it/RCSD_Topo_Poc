from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point, shape

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessDirectionRole,
    AccessStructuralRole,
    AttachmentEndpoint,
    AttachmentInstruction,
    AttachmentTargetKind,
    FrozenSegmentAccessContract,
    GeometrySlice,
    MaterializationError,
    NodeRecipe,
    NodeRecipeKind,
    RoadInstruction,
    SegmentAccessBinding,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
    SourceNodeRecord,
    SourceRoadRecord,
    materialize_target_a_roadgraph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    RoadRole,
    RoadSource,
    SegmentDecision,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


@dataclass(frozen=True)
class MaterializerAuditConfig:
    label_store_root: Path
    output_root: Path
    run_id: str
    expected_crs: str = "EPSG:3857"
    coordinate_tolerance_m: float = 0.05
    strict_hashes: bool = True
    case_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class SegmentBlocker:
    segment_id: str
    code: str
    detail: str


def run_target_a_fallback_materializer_audit(
    config: MaterializerAuditConfig,
) -> dict[str, Any]:
    """Audit deterministic SWSD fallback execution without repairing T01 facts.

    The audit materializes the largest dependency-complete subset whose frozen
    access and independent-Road facts are explicit. A blocked Segment is
    reported locally and is never used to expand fallback scope.
    """
    started = time.perf_counter()
    label_root = normalize_runtime_path(config.label_store_root).resolve(strict=True)
    run_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    run_root.mkdir(parents=True, exist_ok=False)
    inventory = _read_jsonl(label_root / "case_inventory.jsonl")
    if config.case_keys:
        requested = set(config.case_keys)
        inventory = [
            row for row in inventory if str(row["case_key"]) in requested
        ]
        observed = {str(row["case_key"]) for row in inventory}
        if observed != requested:
            raise MaterializationError(
                f"requested audit Cases are absent: {sorted(requested - observed)}"
            )
    case_rows: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    total_frozen_segments = 0
    total_materialized_segments = 0
    total_materialized_roads = 0
    for inventory_row in sorted(inventory, key=lambda row: str(row["case_key"])):
        case_started = time.perf_counter()
        skeleton_path = label_root / str(inventory_row["frozen_skeleton"])
        skeleton = _read_json(skeleton_path)
        case_key = str(skeleton["case_key"])
        expected_segments = {
            str(row["segment_id"]) for row in skeleton.get("segments", ())
        }
        total_frozen_segments += len(expected_segments)
        roads_path = _single_evidence_path(skeleton, "t01_roads")
        nodes_path = roads_path.with_name("nodes.gpkg")
        _validate_source_hashes(
            skeleton,
            roads_path=roads_path,
            nodes_path=nodes_path,
            strict_hashes=config.strict_hashes,
        )
        source_failure = ""
        try:
            source_roads, source_nodes, unusable_roads = _load_source_graph(
                roads_path,
                nodes_path,
            )
        except (MaterializationError, OSError, ValueError) as exc:
            source_failure = str(exc)
            source_roads = {}
            source_nodes = {}
            unusable_roads = {}
            plans = ()
            frozen_access_contracts = ()
            blockers = (
                SegmentBlocker(
                    segment_id="",
                    code="SOURCE_GRAPH_INVALID",
                    detail=source_failure,
                ),
            )
        else:
            (
                plans,
                frozen_access_contracts,
                blockers,
            ) = build_t01_fallback_materialization_instructions(
                skeleton,
                source_roads=source_roads,
                source_nodes=source_nodes,
            )
            affected_segments = {
                str(segment["segment_id"])
                for segment in skeleton.get("segments", ())
                if set(map(str, segment.get("swsd_road_ids", ())))
                & unusable_roads.keys()
            }
            if affected_segments:
                blockers = tuple(
                    row
                    for row in blockers
                    if row.segment_id not in affected_segments
                ) + tuple(
                    SegmentBlocker(
                        segment_id=segment_id,
                        code="SOURCE_ROAD_GEOMETRY_UNSUPPORTED",
                        detail="; ".join(
                            unusable_roads[road_id]
                            for road_id in sorted(
                                set(
                                    map(
                                        str,
                                        next(
                                            row
                                            for row in skeleton["segments"]
                                            if str(row["segment_id"]) == segment_id
                                        ).get("swsd_road_ids", ()),
                                    )
                                )
                                & unusable_roads.keys()
                            )
                        ),
                    )
                    for segment_id in sorted(affected_segments)
                )
        dependency_segments = {row.segment_id for row in plans}
        graph = None
        hard_failure = source_failure
        if plans:
            try:
                graph = materialize_target_a_roadgraph(
                    frozen_segment_ids=sorted(dependency_segments),
                    frozen_access_contracts=frozen_access_contracts,
                    segment_instructions=plans,
                    source_roads=source_roads,
                    source_nodes=source_nodes,
                    expected_crs=config.expected_crs,
                    coordinate_tolerance_m=config.coordinate_tolerance_m,
                )
            except MaterializationError as exc:
                hard_failure = str(exc)
                blockers = tuple(blockers) + (
                    SegmentBlocker(
                        segment_id="",
                        code="MATERIALIZATION_HARD_FAILURE",
                        detail=hard_failure,
                    ),
                )
        blocker_counts.update(row.code for row in blockers)
        if graph is not None:
            total_materialized_segments += len(dependency_segments)
            total_materialized_roads += len(graph.roads)
        case_rows.append(
            {
                "case_key": case_key,
                "frozen_segment_count": len(expected_segments),
                "materialized_segment_count": (
                    len(dependency_segments) if graph is not None else 0
                ),
                "blocked_segment_count": len(
                    {row.segment_id for row in blockers if row.segment_id}
                ),
                "blocked_segments": [asdict(row) for row in blockers],
                "full_frozen_skeleton_materialized": (
                    graph is not None
                    and dependency_segments == expected_segments
                    and not blockers
                ),
                "eligible_dependency_subgraph_materialized": graph is not None,
                "road_count": len(graph.roads) if graph is not None else 0,
                "node_count": len(graph.nodes) if graph is not None else 0,
                "directed_edge_count": (
                    len(graph.directed_edges) if graph is not None else 0
                ),
                "access_binding_count": (
                    len(graph.access_bindings) if graph is not None else 0
                ),
                "fallback_segment_count": (
                    len(graph.fallback_segment_ids) if graph is not None else 0
                ),
                "positive_keep_segment_count": (
                    len(graph.positive_keep_segment_ids) if graph is not None else 0
                ),
                "crs": graph.crs if graph is not None else "",
                "skeleton_mutation_count": (
                    graph.skeleton_mutation_count if graph is not None else 0
                ),
                "silent_fix": graph.silent_fix if graph is not None else False,
                "content_repair": graph.content_repair if graph is not None else False,
                "hard_failure": hard_failure,
                "source_unusable_road_count": len(unusable_roads),
                "input_sha256": {
                    "frozen_skeleton": sha256_file(skeleton_path),
                    "t01_roads": sha256_file(roads_path),
                    "t01_nodes": sha256_file(nodes_path),
                },
                "runtime_seconds": round(time.perf_counter() - case_started, 6),
            }
        )
    summary = {
        "run_id": config.run_id,
        "case_count": len(case_rows),
        "full_frozen_skeleton_materialized_case_count": sum(
            bool(row["full_frozen_skeleton_materialized"]) for row in case_rows
        ),
        "eligible_dependency_subgraph_materialized_case_count": sum(
            bool(row["eligible_dependency_subgraph_materialized"]) for row in case_rows
        ),
        "materialization_hard_failure_case_count": sum(
            bool(row["hard_failure"]) for row in case_rows
        ),
        "frozen_segment_count": total_frozen_segments,
        "materialized_segment_count": total_materialized_segments,
        "materialized_road_count": total_materialized_roads,
        "source_unusable_road_count": sum(
            int(row["source_unusable_road_count"]) for row in case_rows
        ),
        "blocked_segment_count": sum(
            int(row["blocked_segment_count"]) for row in case_rows
        ),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "all_crs_metric_and_consistent": all(
            not row["crs"]
            or _canonical_crs(str(row["crs"]))
            == _canonical_crs(config.expected_crs)
            for row in case_rows
        ),
        "skeleton_mutation_count": sum(
            int(row["skeleton_mutation_count"]) for row in case_rows
        ),
        "silent_fix_count": sum(bool(row["silent_fix"]) for row in case_rows),
        "content_repair_count": sum(
            bool(row["content_repair"]) for row in case_rows
        ),
        "runtime_seconds": round(time.perf_counter() - started, 6),
    }
    _write_jsonl(run_root / "case_audit.jsonl", case_rows)
    _write_json(run_root / "summary.json", summary)
    return summary


def build_t01_fallback_materialization_instructions(
    skeleton: Mapping[str, Any],
    *,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
) -> tuple[
    tuple[SegmentMaterializationInstruction, ...],
    tuple[FrozenSegmentAccessContract, ...],
    tuple[SegmentBlocker, ...],
]:
    """Translate explicit T01 fallback facts into an executable ledger."""
    segment_rows = {
        str(row["segment_id"]): row for row in skeleton.get("segments", ())
    }
    road_records = {
        key[1]: value
        for key, value in source_roads.items()
        if key[0] is RoadSource.SWSD
    }
    node_records = {
        key[1]: value
        for key, value in source_nodes.items()
        if key[0] is RoadSource.SWSD
    }
    node_closures = _node_access_closures(node_records)
    advance_right_access_nodes: dict[str, set[str]] = defaultdict(set)
    for row in segment_rows.values():
        if str(row.get("segment_type")) != "ADVANCE_RIGHT":
            continue
        for field in ("source_segment_access", "target_segment_access"):
            try:
                owner_segment_id, access_node_id = _parse_segment_access(
                    str(row.get(field) or "")
                )
            except MaterializationError:
                continue
            advance_right_access_nodes[owner_segment_id].add(access_node_id)
    road_instruction_ids: dict[tuple[str, str], str] = {}
    ordinary_access_bindings: dict[tuple[str, str], SegmentAccessBinding] = {}
    contracts_by_id: dict[str, FrozenSegmentAccessContract] = {}
    plans_by_segment: dict[str, SegmentMaterializationInstruction] = {}
    blockers: list[SegmentBlocker] = []
    for segment_id, row in sorted(segment_rows.items()):
        if str(row.get("segment_type")) != "STANDARD":
            continue
        blocker = _frozen_plan_blocker(row)
        if blocker is not None:
            blockers.append(blocker)
            continue
        try:
            road_instructions = _road_instructions(
                segment_id,
                row,
                road_records=road_records,
                role=RoadRole.MAIN,
            )
            pair_nodes = tuple(str(value) for value in row.get("pair_nodes", ()))
            if len(pair_nodes) != 2:
                raise MaterializationError(
                    "ordinary Segment must expose exactly two pair_nodes"
                )
            for instruction in road_instructions:
                source_road_id = instruction.geometry_slices[0].source_road_id
                road_instruction_ids[(segment_id, source_road_id)] = (
                    instruction.instruction_id
                )
            binding_specs = [
                (pair_nodes[0], AccessStructuralRole.ENDPOINT),
                (pair_nodes[1], AccessStructuralRole.ENDPOINT),
            ]
            binding_specs.extend(
                (
                    _text(node_id),
                    AccessStructuralRole.THROUGH,
                )
                for node_id in row.get("junc_nodes", ())
                if _text(node_id) not in pair_nodes
            )
            access_bindings: list[SegmentAccessBinding] = []
            segment_binding_by_node: dict[
                tuple[str, str], SegmentAccessBinding
            ] = {}
            segment_contracts: dict[str, FrozenSegmentAccessContract] = {}
            for node_id, structural_role in binding_specs:
                binding, contract = _complete_access_binding(
                    segment_id,
                    node_id,
                    structural_role,
                    row,
                    road_records=road_records,
                    node_records=node_records,
                    node_closures=node_closures,
                    road_instruction_ids=road_instruction_ids,
                )
                if binding.binding_id in segment_contracts:
                    raise MaterializationError(
                        "T01 repeats one Junction-Segment access relation"
                    )
                access_bindings.append(binding)
                segment_binding_by_node[(segment_id, node_id)] = binding
                segment_contracts[contract.binding_id] = contract
            covered_nodes = {
                recipe.source_node_id
                for binding in access_bindings
                for recipe in binding.node_recipes
                if recipe.source_node_id
            }
            for node_id in sorted(
                advance_right_access_nodes.get(segment_id, set())
            ):
                requested_closure = node_closures.get(
                    node_id, frozenset({node_id})
                )
                if requested_closure & covered_nodes:
                    continue
                try:
                    binding, contract = _complete_access_binding(
                        segment_id,
                        node_id,
                        AccessStructuralRole.ADVANCE_RIGHT_ATTACHMENT,
                        row,
                        road_records=road_records,
                        node_records=node_records,
                        node_closures=node_closures,
                        road_instruction_ids=road_instruction_ids,
                    )
                except MaterializationError:
                    continue
                access_bindings.append(binding)
                segment_binding_by_node[(segment_id, node_id)] = binding
                segment_contracts[contract.binding_id] = contract
                covered_nodes.update(
                    recipe.source_node_id
                    for recipe in binding.node_recipes
                    if recipe.source_node_id
                )
            plans_by_segment[segment_id] = SegmentMaterializationInstruction(
                segment_id=segment_id,
                segment_type=SegmentMaterializationType.STANDARD,
                decision=SegmentDecision.ABSTAIN,
                roads=road_instructions,
                access_bindings=tuple(access_bindings),
                fallback_applied=True,
            )
            ordinary_access_bindings.update(segment_binding_by_node)
            contracts_by_id.update(segment_contracts)
        except MaterializationError as exc:
            blockers.append(
                SegmentBlocker(
                    segment_id,
                    "STANDARD_LEDGER_UNRESOLVED",
                    str(exc),
                )
            )
    for segment_id, row in sorted(segment_rows.items()):
        if str(row.get("segment_type")) != "ADVANCE_RIGHT":
            continue
        blocker = _frozen_plan_blocker(row)
        if blocker is not None:
            blockers.append(blocker)
            continue
        try:
            source_segment_id, source_node_id = _parse_segment_access(
                str(row.get("source_segment_access") or "")
            )
            target_segment_id, target_node_id = _parse_segment_access(
                str(row.get("target_segment_access") or "")
            )
            if (
                source_segment_id not in plans_by_segment
                or target_segment_id not in plans_by_segment
            ):
                raise MaterializationError(
                    "AdvanceRight adjacent ordinary fallback is not materializable"
                )
            source_binding = _resolve_access_binding(
                source_segment_id,
                source_node_id,
                ordinary_access_bindings=ordinary_access_bindings,
                node_closures=node_closures,
            )
            target_binding = _resolve_access_binding(
                target_segment_id,
                target_node_id,
                ordinary_access_bindings=ordinary_access_bindings,
                node_closures=node_closures,
            )
            road_instructions = _road_instructions(
                segment_id,
                row,
                road_records=road_records,
                role=RoadRole.ADVANCE_RIGHT,
            )
            child_by_terminal = _advance_right_terminal_instructions(
                road_instructions,
                road_records=road_records,
            )
            attachments = (
                _frozen_node_attachment(
                    side=AttachmentEndpoint.SOURCE,
                    child_segment_id=segment_id,
                    access_node_id=source_node_id,
                    parent_binding=source_binding,
                    child_by_terminal=child_by_terminal,
                    node_closures=node_closures,
                ),
                _frozen_node_attachment(
                    side=AttachmentEndpoint.TARGET,
                    child_segment_id=segment_id,
                    access_node_id=target_node_id,
                    parent_binding=target_binding,
                    child_by_terminal=child_by_terminal,
                    node_closures=node_closures,
                ),
            )
            plans_by_segment[segment_id] = SegmentMaterializationInstruction(
                segment_id=segment_id,
                segment_type=SegmentMaterializationType.ADVANCE_RIGHT,
                decision=SegmentDecision.ABSTAIN,
                roads=road_instructions,
                attachments=attachments,
                fallback_applied=True,
            )
        except (KeyError, MaterializationError) as exc:
            blockers.append(
                SegmentBlocker(
                    segment_id,
                    "ADVANCE_RIGHT_LEDGER_UNRESOLVED",
                    str(exc),
                )
            )
    return (
        tuple(plans_by_segment[key] for key in sorted(plans_by_segment)),
        tuple(contracts_by_id[key] for key in sorted(contracts_by_id)),
        tuple(sorted(blockers, key=lambda row: (row.segment_id, row.code, row.detail))),
    )


def _road_instructions(
    segment_id: str,
    segment: Mapping[str, Any],
    *,
    road_records: Mapping[str, SourceRoadRecord],
    role: RoadRole,
) -> tuple[RoadInstruction, ...]:
    instructions: list[RoadInstruction] = []
    for road_id in sorted(str(value) for value in segment.get("swsd_road_ids", ())):
        road = road_records.get(road_id)
        if road is None:
            raise MaterializationError(f"T01 Road is absent: {road_id}")
        instruction_id = f"swsd:{segment_id}:{road_id}"
        instructions.append(
            RoadInstruction(
                instruction_id=instruction_id,
                owner_segment_id=segment_id,
                role=role,
                direction=road.direction,
                geometry_slices=(
                    GeometrySlice(
                        source_kind=RoadSource.SWSD,
                        source_road_id=road_id,
                    ),
                ),
                source_node_recipe=_copy_node_recipe(road.start_node_id),
                target_node_recipe=_copy_node_recipe(road.end_node_id),
                output_road_id=road_id,
            )
        )
    if not instructions:
        raise MaterializationError("frozen Segment has no SWSD Road")
    return tuple(instructions)


def _copy_node_recipe(node_id: str) -> NodeRecipe:
    return NodeRecipe(
        kind=NodeRecipeKind.COPY_SOURCE_NODE,
        source_kind=RoadSource.SWSD,
        source_node_id=node_id,
        output_node_id=node_id,
    )


def _frozen_plan_blocker(segment: Mapping[str, Any]) -> SegmentBlocker | None:
    segment_id = str(segment["segment_id"])
    if not bool(segment.get("independent_road_valid")):
        return SegmentBlocker(
            segment_id,
            "FROZEN_INDEPENDENT_ROAD_INVALID",
            "T01 does not contain a legal independent SWSD Road plan",
        )
    if not bool(segment.get("access_valid")):
        return SegmentBlocker(
            segment_id,
            "FROZEN_ACCESS_INVALID",
            "T01 does not contain a legal frozen Segment access relation",
        )
    return None


def _parse_segment_access(value: str) -> tuple[str, str]:
    segment_id, separator, node_id = value.rpartition("@")
    if not separator or not segment_id or not node_id:
        raise MaterializationError("frozen Segment access is incomplete")
    return segment_id, node_id


def _complete_access_binding(
    segment_id: str,
    node_id: str,
    structural_role: AccessStructuralRole,
    segment: Mapping[str, Any],
    *,
    road_records: Mapping[str, SourceRoadRecord],
    node_records: Mapping[str, SourceNodeRecord],
    node_closures: Mapping[str, frozenset[str]],
    road_instruction_ids: Mapping[tuple[str, str], str],
) -> tuple[SegmentAccessBinding, FrozenSegmentAccessContract]:
    if node_id not in node_records:
        raise MaterializationError(
            f"T01 access Node is absent: {segment_id}@{node_id}"
        )
    closure = node_closures.get(node_id, frozenset({node_id}))
    candidates = [
        str(road_id)
        for road_id in segment.get("swsd_road_ids", ())
        if str(road_id) in road_records
        and (
            road_records[str(road_id)].start_node_id in closure
            or road_records[str(road_id)].end_node_id in closure
        )
    ]
    if not candidates:
        raise MaterializationError(
            f"access has no owned Road for {segment_id}@{node_id}"
        )
    direction_roles: set[AccessDirectionRole] = set()
    for road_id in candidates:
        road = road_records[road_id]
        direction_roles.update(
            _source_access_direction_roles(
                road,
                source_match=road.start_node_id in closure,
                target_match=road.end_node_id in closure,
            )
        )
    direction_role = _combined_access_direction_role(direction_roles)
    binding_id = f"{segment_id}@{node_id}"
    binding = SegmentAccessBinding(
        binding_id=binding_id,
        segment_id=segment_id,
        access_node_id=node_id,
        structural_role=structural_role,
        direction_role=direction_role,
        road_instruction_ids=tuple(
            road_instruction_ids[(segment_id, road_id)]
            for road_id in sorted(candidates)
        ),
        node_recipes=tuple(
            _copy_node_recipe(closure_node_id)
            for closure_node_id in sorted(closure)
            if closure_node_id in node_records
        ),
    )
    contract = FrozenSegmentAccessContract(
        binding_id=binding_id,
        segment_id=segment_id,
        access_node_id=node_id,
        structural_role=structural_role,
        direction_role=direction_role,
    )
    return binding, contract


def _source_access_direction_roles(
    road: SourceRoadRecord,
    *,
    source_match: bool,
    target_match: bool,
) -> set[AccessDirectionRole]:
    roles: set[AccessDirectionRole] = set()
    if road.direction in {0, 1, 2}:
        if source_match:
            roles.add(AccessDirectionRole.EXIT)
        if target_match:
            roles.add(AccessDirectionRole.ENTER)
    if road.direction in {0, 1, 3}:
        if source_match:
            roles.add(AccessDirectionRole.ENTER)
        if target_match:
            roles.add(AccessDirectionRole.EXIT)
    return roles


def _combined_access_direction_role(
    roles: set[AccessDirectionRole],
) -> AccessDirectionRole:
    if roles == {AccessDirectionRole.ENTER}:
        return AccessDirectionRole.ENTER
    if roles == {AccessDirectionRole.EXIT}:
        return AccessDirectionRole.EXIT
    if roles == {AccessDirectionRole.ENTER, AccessDirectionRole.EXIT}:
        return AccessDirectionRole.BOTH
    raise MaterializationError("T01 access has no valid directed Road incidence")


def _resolve_access_binding(
    segment_id: str,
    node_id: str,
    *,
    ordinary_access_bindings: Mapping[
        tuple[str, str], SegmentAccessBinding
    ],
    node_closures: Mapping[str, frozenset[str]],
) -> SegmentAccessBinding:
    direct = ordinary_access_bindings.get((segment_id, node_id))
    if direct is not None:
        return direct
    requested_closure = node_closures.get(node_id, frozenset({node_id}))
    candidates = [
        binding
        for (candidate_segment_id, _), binding in ordinary_access_bindings.items()
        if candidate_segment_id == segment_id
        and requested_closure
        & {
            recipe.source_node_id
            for recipe in binding.node_recipes
            if recipe.source_node_id
        }
    ]
    if len(candidates) != 1:
        raise MaterializationError(
            f"frozen access binding is not unique for {segment_id}@{node_id}: "
            f"{sorted(row.binding_id for row in candidates)}"
        )
    return candidates[0]


def _advance_right_terminal_instructions(
    instructions: Sequence[RoadInstruction],
    *,
    road_records: Mapping[str, SourceRoadRecord],
) -> dict[str, RoadInstruction]:
    degree: Counter[str] = Counter()
    instruction_by_terminal: dict[str, list[RoadInstruction]] = defaultdict(list)
    for instruction in instructions:
        road_id = instruction.geometry_slices[0].source_road_id
        road = road_records[road_id]
        degree[road.start_node_id] += 1
        degree[road.end_node_id] += 1
        instruction_by_terminal[road.start_node_id].append(instruction)
        instruction_by_terminal[road.end_node_id].append(instruction)
    result: dict[str, RoadInstruction] = {}
    for node_id, count in degree.items():
        if count != 1:
            continue
        rows = instruction_by_terminal[node_id]
        if len(rows) == 1:
            result[node_id] = rows[0]
    return result


def _frozen_node_attachment(
    *,
    side: AttachmentEndpoint,
    child_segment_id: str,
    access_node_id: str,
    parent_binding: SegmentAccessBinding,
    child_by_terminal: Mapping[str, RoadInstruction],
    node_closures: Mapping[str, frozenset[str]],
) -> AttachmentInstruction:
    closure = node_closures.get(access_node_id, frozenset({access_node_id}))
    terminal_ids = sorted(set(child_by_terminal) & set(closure))
    if len(terminal_ids) != 1:
        raise MaterializationError(
            f"AdvanceRight terminal is not unique for {access_node_id}: "
            f"{terminal_ids}"
        )
    terminal_node_id = terminal_ids[0]
    if terminal_node_id not in {
        recipe.source_node_id
        for recipe in parent_binding.node_recipes
        if recipe.source_node_id
    }:
        raise MaterializationError(
            "AdvanceRight frozen terminal is outside adjacent access Nodes"
        )
    child_instruction = child_by_terminal[terminal_node_id]
    if child_instruction.source_node_recipe.source_node_id == terminal_node_id:
        endpoint = AttachmentEndpoint.SOURCE
    elif child_instruction.target_node_recipe.source_node_id == terminal_node_id:
        endpoint = AttachmentEndpoint.TARGET
    else:
        raise MaterializationError(
            f"AdvanceRight Road does not terminate at {terminal_node_id}"
        )
    return AttachmentInstruction(
        side=side,
        parent_access_binding_id=parent_binding.binding_id,
        child_road_instruction_id=child_instruction.instruction_id,
        child_segment_id=child_segment_id,
        child_endpoint=endpoint,
        target_kind=AttachmentTargetKind.FROZEN_ACCESS_NODE,
        target_node_id=terminal_node_id,
    )


def _node_access_closures(
    nodes: Mapping[str, SourceNodeRecord],
) -> dict[str, frozenset[str]]:
    main_members: dict[str, set[str]] = defaultdict(set)
    for node_id, node in nodes.items():
        main = _nonzero((node.properties or {}).get("mainnodeid"))
        if main:
            main_members[main].add(node_id)
    result: dict[str, frozenset[str]] = {}
    for node_id, node in nodes.items():
        closure = {node_id}
        properties = node.properties or {}
        closure.update(_string_list(properties.get("subnodeid")))
        main = _nonzero(properties.get("mainnodeid"))
        if main:
            closure.add(main)
            closure.update(main_members.get(main, set()))
        closure.update(main_members.get(node_id, set()))
        result[node_id] = frozenset(closure & nodes.keys())
    return result


def _load_source_graph(
    roads_path: Path,
    nodes_path: Path,
) -> tuple[
    dict[tuple[RoadSource, str], SourceRoadRecord],
    dict[tuple[RoadSource, str], SourceNodeRecord],
    dict[str, str],
]:
    roads: dict[tuple[RoadSource, str], SourceRoadRecord] = {}
    unusable_roads: dict[str, str] = {}
    with fiona.open(roads_path) as source:
        crs = _canonical_crs(source.crs_wkt or source.crs)
        for feature in source:
            properties = dict(feature["properties"])
            road_id = _text(properties.get("id"))
            geometry = shape(feature["geometry"])
            if not isinstance(geometry, LineString):
                unusable_roads[road_id] = (
                    "T01 Road source contains a non-LineString: "
                    f"road_id={road_id}, geometry_type={geometry.geom_type}"
                )
                continue
            key = (RoadSource.SWSD, road_id)
            if key in roads:
                raise MaterializationError(f"T01 Road id is duplicated: {road_id}")
            roads[key] = SourceRoadRecord(
                source_kind=RoadSource.SWSD,
                source_road_id=road_id,
                geometry=geometry,
                start_node_id=_text(properties.get("snodeid")),
                end_node_id=_text(properties.get("enodeid")),
                direction=int(properties.get("direction")),
                crs=crs,
                properties=properties,
            )
    nodes: dict[tuple[RoadSource, str], SourceNodeRecord] = {}
    with fiona.open(nodes_path) as source:
        crs = _canonical_crs(source.crs_wkt or source.crs)
        for feature in source:
            properties = dict(feature["properties"])
            node_id = _text(properties.get("id"))
            geometry = shape(feature["geometry"])
            if not isinstance(geometry, Point):
                raise MaterializationError("T01 Node source contains a non-Point")
            key = (RoadSource.SWSD, node_id)
            if key in nodes:
                raise MaterializationError(f"T01 Node id is duplicated: {node_id}")
            nodes[key] = SourceNodeRecord(
                source_kind=RoadSource.SWSD,
                source_node_id=node_id,
                geometry=geometry,
                crs=crs,
                properties=properties,
            )
    return roads, nodes, unusable_roads


def _single_evidence_path(
    skeleton: Mapping[str, Any],
    role: str,
) -> Path:
    paths = {
        normalize_runtime_path(str(ref["path"])).resolve(strict=True)
        for segment in skeleton.get("segments", ())
        for ref in segment.get("evidence_refs", ())
        if str(ref.get("role")) == role
    }
    if len(paths) != 1:
        raise MaterializationError(
            f"case must resolve exactly one {role} source: {sorted(map(str, paths))}"
        )
    return next(iter(paths))


def _validate_source_hashes(
    skeleton: Mapping[str, Any],
    *,
    roads_path: Path,
    nodes_path: Path,
    strict_hashes: bool,
) -> None:
    if not strict_hashes:
        return
    hashes = {str(key): str(value) for key, value in skeleton["source_hashes"]}
    observed = {
        "t01_roads": sha256_file(roads_path),
        "t01_nodes": sha256_file(nodes_path),
    }
    mismatches = {
        key: {"expected": hashes.get(key), "observed": value}
        for key, value in observed.items()
        if hashes.get(key) != value
    }
    if mismatches:
        raise MaterializationError(f"T01 source hash mismatch: {mismatches}")


def _canonical_crs(value: Any) -> str:
    crs = CRS.from_user_input(value)
    authority = crs.to_authority()
    return (
        f"{authority[0]}:{authority[1]}"
        if authority
        else crs.to_wkt()
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _nonzero(value: Any) -> str:
    text = _text(value)
    return "" if text in {"", "0", "0.0"} else text


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_text(item) for item in value if _text(item)]
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in text.split(",") if item.strip()]
    if not isinstance(parsed, list):
        parsed = [parsed]
    return [_text(item) for item in parsed if _text(item)]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


__all__ = [
    "MaterializerAuditConfig",
    "SegmentBlocker",
    "build_t01_fallback_materialization_instructions",
    "run_target_a_fallback_materializer_audit",
]
