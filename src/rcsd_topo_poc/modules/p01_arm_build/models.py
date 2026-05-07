from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry


DATASETS = ("SWSD", "RCSD", "FRCSD")
THROUGH_STATUSES = (
    "simple_through",
    "t_mainline_through",
    "t_side_terminal",
    "semantic_boundary",
    "ambiguous_boundary",
    "dead_end",
    "patch_boundary",
    "loop_to_current_junction",
)


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    mainnodeid: str | None
    kind: str | None
    geometry: BaseGeometry
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoadRecord:
    road_id: str
    snodeid: str
    enodeid: str
    direction: int | None
    formway: str | None
    geometry: BaseGeometry
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorLayer:
    path: Path
    crs: Any
    crs_wkt: str | None
    schema_properties: tuple[str, ...]
    feature_count: int


@dataclass(frozen=True)
class DatasetInput:
    dataset: str
    nodes_path: Path
    roads_path: Path


@dataclass(frozen=True)
class LoadedDataset:
    dataset: str
    nodes: dict[str, NodeRecord]
    roads: dict[str, RoadRecord]
    node_layer: VectorLayer
    road_layer: VectorLayer


@dataclass(frozen=True)
class JunctionGroup:
    group_id: str
    group_index: int
    swsd_junction_id: str
    rcsd_junction_id: str
    frcsd_junction_id: str

    def junction_id_for(self, dataset: str) -> str:
        if dataset == "SWSD":
            return self.swsd_junction_id
        if dataset == "RCSD":
            return self.rcsd_junction_id
        if dataset == "FRCSD":
            return self.frcsd_junction_id
        raise ValueError(f"Unknown dataset: {dataset}")


@dataclass(frozen=True)
class JunctionContext:
    dataset: str
    junction_id: str
    member_node_ids: tuple[str, ...]
    internal_road_ids: tuple[str, ...]
    inbound_seed_road_ids: tuple[str, ...]
    outbound_seed_road_ids: tuple[str, ...]
    bidirectional_seed_road_ids: tuple[str, ...]
    excluded_right_turn_road_ids: tuple[str, ...]
    input_issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class ThroughDecisionAudit:
    dataset: str
    current_junction_id: str
    trace_id: str
    node_group_id: str
    member_node_ids: tuple[str, ...]
    incoming_road_id: str
    outgoing_road_id: str | None
    status: str
    decision_reason: str
    incident_road_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArmTrace:
    dataset: str
    current_junction_id: str
    trace_id: str
    seed_road_id: str
    seed_role: str
    traced_road_ids: tuple[str, ...]
    traced_node_ids: tuple[str, ...]
    through_decisions: tuple[str, ...]
    stop_type: str
    stop_reason: str
    assigned_initial_arm_id: str | None
    issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class InitialArm:
    dataset: str
    current_junction_id: str
    initial_arm_id: str
    terminal_type: str
    terminal_junction_id: str | None
    terminal_member_node_ids: tuple[str, ...]
    member_road_ids: tuple[str, ...]
    seed_road_ids: tuple[str, ...]
    connector_road_ids: tuple[str, ...]
    inbound_member_road_ids: tuple[str, ...]
    outbound_member_road_ids: tuple[str, ...]
    bidirectional_member_road_ids: tuple[str, ...]
    build_status: str
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class LocalArmCandidate:
    dataset: str
    current_junction_id: str
    local_arm_candidate_id: str
    source_seed_road_ids: tuple[str, ...]
    source_initial_arm_ids: tuple[str, ...]
    local_stub_road_ids: tuple[str, ...]
    inbound_seed_road_ids: tuple[str, ...]
    outbound_seed_road_ids: tuple[str, ...]
    bidirectional_seed_road_ids: tuple[str, ...]
    member_node_ids: tuple[str, ...]
    trend_angle_deg: float
    angular_spread_deg: float
    grouping_reason: str
    build_status: str
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class FinalArm:
    dataset: str
    current_junction_id: str
    final_arm_id: str
    source_initial_arm_ids: tuple[str, ...]
    merge_status: str
    merge_reason: str
    initial_arm: dict[str, Any]


@dataclass(frozen=True)
class IssueReport:
    dataset: str
    current_junction_id: str
    issues: tuple[dict[str, Any], ...]
    issue_counts: dict[str, int]


@dataclass(frozen=True)
class DatasetBuildResult:
    dataset: str
    junction_id: str
    context: JunctionContext
    initial_arms: tuple[InitialArm, ...]
    final_arms: tuple[FinalArm, ...]
    local_arm_candidates: tuple[LocalArmCandidate, ...]
    traces: tuple[ArmTrace, ...]
    decisions: tuple[ThroughDecisionAudit, ...]
    issue_report: IssueReport
    review_priority: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class CaseBuildResult:
    group: JunctionGroup
    datasets: dict[str, DatasetBuildResult]
    compare_summary: dict[str, Any]


def to_plain(value: Any) -> Any:
    if hasattr(value, "__geo_interface__"):
        return value.__geo_interface__
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value
