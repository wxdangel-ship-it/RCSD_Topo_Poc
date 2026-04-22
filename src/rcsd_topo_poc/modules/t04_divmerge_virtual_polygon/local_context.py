from __future__ import annotations

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step2_local_context import (
    _build_stage4_local_context,
)

from .case_models import T04CaseBundle


def build_step2_local_context(
    *,
    case_bundle: T04CaseBundle,
    representative_node,
    group_nodes,
):
    return _build_stage4_local_context(
        representative_node=representative_node,
        group_nodes=list(group_nodes),
        nodes=list(case_bundle.nodes),
        roads=list(case_bundle.roads),
        drivezone_features=list(case_bundle.drivezone_features),
        rcsd_roads=list(case_bundle.rcsd_roads),
        rcsd_nodes=list(case_bundle.rcsd_nodes),
        divstripzone_path=case_bundle.case_spec.input_paths["divstripzone_path"],
        divstripzone_layer=None,
        divstripzone_crs=None,
    )
