from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arm_builder import build_swsd_arms
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.io import (
    T09LoadedInputs,
    annotate_arm_angles,
    load_t09_inputs,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.movement_builder import build_arm_movements
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.outputs import (
    T09OutputArtifacts,
    write_restoration_outputs,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restoration import restore_field_rules
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    RestorationResult,
    SWSDRoadInput,
    T09ArmMovement,
    T09SwsdArm,
    to_jsonable,
)


@dataclass(frozen=True)
class T09RunResult:
    result: RestorationResult
    artifacts: T09OutputArtifacts


def run_t09_swsd_field_rule_restoration(
    *,
    swnode_gpkg: str | Path,
    swroad_gpkg: str | Path,
    segment_gpkg: str | Path | None,
    output_dir: str | Path,
    restriction_gpkg: str | Path | None = None,
    arrow_gpkg: str | Path | None = None,
    run_id: str | None = None,
    swnode_layer: str | None = None,
    swroad_layer: str | None = None,
    segment_layer: str | None = None,
    restriction_layer: str | None = None,
    arrow_layer: str | None = None,
    target_epsg: int = 3857,
) -> T09RunResult:
    started = time.perf_counter()
    effective_run_id = run_id or _default_run_id()
    loaded = load_t09_inputs(
        swnode_gpkg=swnode_gpkg,
        swroad_gpkg=swroad_gpkg,
        segment_gpkg=segment_gpkg,
        restriction_gpkg=restriction_gpkg,
        arrow_gpkg=arrow_gpkg,
        swnode_layer=swnode_layer,
        swroad_layer=swroad_layer,
        segment_layer=segment_layer,
        restriction_layer=restriction_layer,
        arrow_layer=arrow_layer,
        target_epsg=target_epsg,
    )
    arms, movements = build_t09_arm_universe(loaded)
    result = restore_field_rules(
        arms=arms,
        movements=movements,
        restrictions=loaded.restrictions,
        arrows=loaded.arrows,
        road_attributes=loaded.road_attributes,
        roads=loaded.roads,
        road_geometries=loaded.road_geometries,
    )
    elapsed_seconds = time.perf_counter() - started
    result = replace(
        result,
        summary=_summary(
            result=result,
            loaded=loaded,
            elapsed_seconds=elapsed_seconds,
            run_id=effective_run_id,
            output_dir=output_dir,
            target_epsg=target_epsg,
        ),
    )
    artifacts = write_restoration_outputs(
        result=result,
        output_dir=Path(output_dir) / effective_run_id,
        road_geometries=loaded.road_geometries,
        crs_text=f"EPSG:{target_epsg}",
    )
    return T09RunResult(result=result, artifacts=artifacts)


def build_t09_arm_universe(loaded: T09LoadedInputs) -> tuple[tuple[T09SwsdArm, ...], tuple[T09ArmMovement, ...]]:
    roads_by_id = {road.road_id: road for road in loaded.roads}
    road_ids_by_node: dict[str, set[str]] = {}
    for road in loaded.roads:
        road_ids_by_node.setdefault(road.snodeid, set()).add(road.road_id)
        road_ids_by_node.setdefault(road.enodeid, set()).add(road.road_id)

    all_arms: list[T09SwsdArm] = []
    all_movements: list[T09ArmMovement] = []
    for junction_id, member_node_ids in sorted(loaded.junction_member_node_ids.items()):
        member_set = set(member_node_ids)
        incident_ids = set()
        for node_id in member_set:
            incident_ids.update(road_ids_by_node.get(node_id, set()))
        junction_roads = tuple(roads_by_id[road_id] for road_id in sorted(incident_ids, key=_sort_key))
        arms = build_swsd_arms(
            junction_id=junction_id,
            member_node_ids=member_node_ids,
            roads=junction_roads,
            segments=loaded.segments,
            road_geometries=loaded.road_geometries,
        )
        arms = annotate_arm_angles(arms, roads_by_id=roads_by_id, road_geometries=loaded.road_geometries)
        movements = build_arm_movements(junction_id=junction_id, arms=arms)
        all_arms.extend(arms)
        all_movements.extend(movements)
    return tuple(all_arms), tuple(all_movements)


def _summary(
    *,
    result: RestorationResult,
    loaded: T09LoadedInputs,
    elapsed_seconds: float,
    run_id: str | None,
    output_dir: str | Path,
    target_epsg: int,
) -> dict[str, Any]:
    summary = dict(result.summary)
    summary.update(
        {
            "tool": "T09 Step1/2",
            "stage": "swsd_field_rule_restoration",
            "run_id": run_id,
            "produced_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "target_epsg": target_epsg,
            "output_dir": str(Path(output_dir).expanduser().resolve()),
            "input_audit": loaded.input_audit,
            "performance": {
                "elapsed_seconds": round(elapsed_seconds, 6),
                "junctions_per_second": _items_per_second(
                    len(loaded.junction_member_node_ids),
                    elapsed_seconds,
                ),
                "movements_per_second": _items_per_second(len(result.movements), elapsed_seconds),
            },
        }
    )
    qa = dict(summary.get("qa", {}))
    qa.update(
        {
            "crs_transform_executed": loaded.crs_transform_executed,
            "crs_note": f"inputs read through vector_io target EPSG:{target_epsg}",
            "topology_silent_fix": False,
            "geometry_semantics": "arm angles derived from seed road geometry and explicit snodeid/enodeid topology",
            "audit_traceability": "restored rules only reference T09EvidenceItem ids",
            "performance_counter_scope": "junction, arm, movement, evidence and output object counts",
        }
    )
    summary["qa"] = qa
    return to_jsonable(summary)


def _default_run_id() -> str:
    return "t09_swsd_field_rule_restoration_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _items_per_second(count: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return float(count)
    return round(count / elapsed_seconds, 6)


def _sort_key(value: str) -> tuple[int, Any]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
