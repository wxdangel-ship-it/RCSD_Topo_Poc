from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from tests.modules.t03_virtual_junction_anchor._case_helpers import node_feature, road_feature, write_case_package


def write_association_case_package(
    case_root: Path,
    case_id: str,
    *,
    kind_2: int = 4,
    roads: list[dict] | None = None,
    extra_nodes: list[dict] | None = None,
    rcsd_roads: list[dict] | None = None,
    rcsd_nodes: list[dict] | None = None,
    drivezone_geometry=None,
    drivezone_geometries: list | None = None,
) -> None:
    write_case_package(
        case_root,
        case_id,
        kind_2=kind_2,
        roads=roads,
        extra_nodes=extra_nodes,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        drivezone_geometry=drivezone_geometry,
        drivezone_geometries=drivezone_geometries,
    )


def write_step3_prerequisite(
    step3_root: Path,
    case_id: str,
    *,
    template_class: str = "center_junction",
    step3_state: str = "established",
    selected_road_ids: list[str] | None = None,
    excluded_road_ids: list[str] | None = None,
    allowed_geometry=None,
    reason: str = "step3_established",
    status_overrides: dict | None = None,
) -> Path:
    case_dir = step3_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    write_vector(
        case_dir / "step3_allowed_space.gpkg",
        [
            {
                "properties": {"case_id": case_id, "layer": "allowed_space"},
                "geometry": allowed_geometry or box(-20.0, -20.0, 20.0, 20.0),
            }
        ],
    )
    status_doc = {
        "case_id": case_id,
        "template_class": template_class,
        "step3_state": step3_state,
        "step3_established": step3_state == "established",
        "reason": reason,
        "visual_review_class": "V1 认可成功" if step3_state == "established" else "V2 业务正确但几何待修",
        "root_cause_layer": None if step3_state == "established" else "step3",
        "root_cause_type": None if step3_state == "established" else reason,
        "key_metrics": {"selected_road_count": len(selected_road_ids or [])},
        "selected_road_ids": list(selected_road_ids or []),
        "excluded_road_ids": list(excluded_road_ids or []),
    }
    if status_overrides:
        status_doc.update(status_overrides)
    audit_doc = {
        "selected_road_ids": list(selected_road_ids or []),
        "excluded_road_ids": list(excluded_road_ids or []),
        "step3_state": step3_state,
        "reason": reason,
    }
    (case_dir / "step3_status.json").write_text(json.dumps(status_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_dir / "step3_audit.json").write_text(json.dumps(audit_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return case_dir


def build_center_case_a(case_root: Path, step3_root: Path, case_id: str = "100001") -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_n_1", 2.0, 2.0, mainnodeid="rc_g_1", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_r_1", "rc_a", "rc_n_1", [(-12.0, 2.0), (12.0, 2.0)]),
        road_feature("rc_r_2", "rc_n_1", "rc_b", [(2.0, -12.0), (2.0, 12.0)]),
        road_feature("rc_r_3", "rc_n_1", "rc_c", [(2.0, 2.0), (12.0, 12.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )


def build_center_case_b(case_root: Path, step3_root: Path, case_id: str = "100002") -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-40.0, 0.0), (40.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -25.0), (0.0, 25.0)]),
    ]
    rcsd_roads = [
        road_feature("rc_r_support", "ra", "rb", [(-60.0, 0.0), (60.0, 0.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-40.0, -12.0, 40.0, 12.0),
    )


def build_center_case_c(case_root: Path, step3_root: Path, case_id: str = "100003") -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_roads = [
        road_feature("rc_r_far", "ra", "rb", [(-80.0, 80.0), (80.0, 80.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )


def build_center_case_degree2_connector(case_root: Path, step3_root: Path, case_id: str = "100004") -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_core", 0.0, 0.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_connector", 10.0, 6.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_far", 14.0, 24.0, mainnodeid="rc_g_far", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_r_left", "rc_left", "rc_core", [(-12.0, 0.0), (0.0, 0.0)]),
        road_feature("rc_r_down", "rc_down", "rc_core", [(0.0, -12.0), (0.0, 0.0)]),
        road_feature("rc_r_connector", "rc_core", "rc_connector", [(0.0, 0.0), (10.0, 6.0)]),
        road_feature("rc_r_tail", "rc_connector", "rc_far", [(10.0, 6.0), (14.0, 24.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )


def build_center_case_degree2_connector_with_true_foreign_node(
    case_root: Path,
    step3_root: Path,
    case_id: str = "100009",
) -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_core", 0.0, 0.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_connector", 10.0, 6.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_tail_end", 14.0, 24.0, mainnodeid="rc_g_far", kind_2=4),
        node_feature("rc_true_foreign", 6.0, 6.0, mainnodeid="rc_g_true_foreign", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_r_left", "rc_left", "rc_core", [(-12.0, 0.0), (0.0, 0.0)]),
        road_feature("rc_r_down", "rc_down", "rc_core", [(0.0, -12.0), (0.0, 0.0)]),
        road_feature("rc_r_connector", "rc_core", "rc_connector", [(0.0, 0.0), (10.0, 6.0)]),
        road_feature("rc_r_tail", "rc_connector", "rc_tail_end", [(10.0, 6.0), (14.0, 24.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )


def build_center_case_degree2_turn_connector(case_root: Path, step3_root: Path, case_id: str = "100008") -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_core", 0.0, 0.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_connector", 10.0, 0.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_turn_end", 10.0, 14.0, mainnodeid="rc_g_turn", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_r_left", "rc_left", "rc_core", [(-12.0, 0.0), (0.0, 0.0)]),
        road_feature("rc_r_down", "rc_down", "rc_core", [(0.0, -12.0), (0.0, 0.0)]),
        road_feature("rc_r_connector", "rc_core", "rc_connector", [(0.0, 0.0), (10.0, 0.0)]),
        road_feature("rc_r_turn", "rc_connector", "rc_turn_end", [(10.0, 0.0), (10.0, 14.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )


def build_center_case_multi_surface_filter(case_root: Path, step3_root: Path, case_id: str = "100005") -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
        road_feature("road_local_foreign", "nf_a", "nf_b", [(-18.0, 10.0), (18.0, 10.0)]),
        road_feature("road_far_surface", "ff_a", "ff_b", [(90.0, 0.0), (120.0, 0.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_n_1", 2.0, 2.0, mainnodeid="rc_g_1", kind_2=4),
        node_feature("rc_n_far", 100.0, 0.0, mainnodeid="rc_g_far", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_r_1", "rc_a", "rc_n_1", [(-12.0, 2.0), (12.0, 2.0)]),
        road_feature("rc_r_2", "rc_n_1", "rc_b", [(2.0, -12.0), (2.0, 12.0)]),
        road_feature("rc_r_3", "rc_n_1", "rc_c", [(2.0, 2.0), (12.0, 12.0)]),
        road_feature("rc_r_far", "rc_far_a", "rc_n_far", [(88.0, 0.0), (112.0, 0.0)]),
    ]
    write_association_case_package(
        case_root / case_id,
        case_id,
        roads=roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        drivezone_geometries=[box(-35.0, -35.0, 35.0, 35.0), box(80.0, -20.0, 125.0, 20.0)],
    )
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )


def build_single_sided_parallel_support_case(case_root: Path, step3_root: Path, case_id: str = "100006") -> None:
    roads = [
        road_feature("road_h_left", case_id, "left_far", [(-20.0, 0.0), (0.0, 0.0)]),
        road_feature("road_h_right", "pair_b", "right_far", [(10.0, 0.0), (25.0, 0.0)]),
        road_feature("road_v_inner", case_id, "v_mid", [(0.0, 0.0), (0.0, 18.0)]),
        road_feature("road_v_outer", "v_mid", "v_far", [(0.0, 18.0), (0.0, 35.0)]),
    ]
    extra_nodes = [
        node_feature("pair_b", 10.0, 0.0, mainnodeid=case_id, kind_2=2048),
    ]
    rcsd_nodes = [
        node_feature("rc_core", -8.0, 0.0, mainnodeid="rc_core", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_required", "rc_far", "rc_core", [(-18.0, 0.0), (-8.0, 0.0)]),
        road_feature("rc_support_exit_side", "rc_exit_a", "rc_exit_b", [(0.0, 0.0), (0.0, 28.0)]),
        road_feature("rc_support_parallel", "rc_parallel_a", "rc_parallel_b", [(2.0, 0.0), (2.0, 28.0)]),
    ]
    write_association_case_package(
        case_root / case_id,
        case_id,
        kind_2=2048,
        roads=roads,
        extra_nodes=extra_nodes,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        drivezone_geometry=box(-30.0, -10.0, 30.0, 40.0),
    )
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="single_sided_t_mouth",
        selected_road_ids=["road_h_left", "road_h_right", "road_v_inner", "road_v_outer"],
        allowed_geometry=box(-18.0, -8.0, 10.0, 30.0),
        status_overrides={
            "single_sided_horizontal_pair_detected": True,
            "single_sided_horizontal_pair_road_ids": ["road_h_left", "road_h_right"],
            "single_sided_direction_resolution_mode": "semantic_horizontal_pair",
            "target_group_node_ids": [case_id, "pair_b"],
        },
    )


def build_center_case_foreign_selected_surface_overlap(
    case_root: Path,
    step3_root: Path,
    case_id: str = "100007",
) -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
        road_feature("road_foreign_parallel", "nf_a", "nf_b", [(-30.0, 11.5), (30.0, 11.5)]),
    ]
    rcsd_nodes = [
        node_feature("rc_n_1", 2.0, 2.0, mainnodeid="rc_g_1", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_r_1", "rc_a", "rc_n_1", [(-12.0, 2.0), (12.0, 2.0)]),
        road_feature("rc_r_2", "rc_n_1", "rc_b", [(2.0, -12.0), (2.0, 12.0)]),
        road_feature("rc_r_3", "rc_n_1", "rc_c", [(2.0, 2.0), (12.0, 12.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-18.0, -18.0, 18.0, 18.0),
    )
