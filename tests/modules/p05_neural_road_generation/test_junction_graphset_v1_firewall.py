from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_firewall import (
    EvidenceStage,
    StageFirewall,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    CandidateBinding,
    JunctionEvidenceExample,
    ObjectTokenSpan,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


def _example(*, requires_grad: bool = False) -> JunctionEvidenceExample:
    refs = (
        ObjectRef(EvidenceRole.SWSD_JUNCTION, "S1"),
        ObjectRef(EvidenceRole.DRIVEZONE, "D1"),
        ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1"),
        ObjectRef(EvidenceRole.RCSD_NODE, "N1"),
        ObjectRef(EvidenceRole.RCSD_ROAD, "R1"),
    )
    tokens = torch.arange(5 * 21, dtype=torch.float32).reshape(5, 21)
    tokens.requires_grad_(requires_grad)
    junction_key = "T03:fixture|S1"
    return JunctionEvidenceExample(
        junction_key=junction_key,
        case_key="T03:fixture",
        semantic_junction_id="S1",
        geometry_tokens=tokens,
        object_spans=tuple(
            ObjectTokenSpan(ref, index, index + 1)
            for index, ref in enumerate(refs)
        ),
        topology_edge_indices=torch.tensor(
            [[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long
        ),
        topology_edge_features=torch.ones((4, 8), dtype=torch.float32),
        candidate_binding=CandidateBinding(
            junction_key=junction_key,
            allowed_object_refs=refs,
            plans=(),
        ),
    )


def test_step1_physically_excludes_every_rcsd_channel() -> None:
    firewall = StageFirewall()
    example = _example()
    step1 = firewall.build_view(example, EvidenceStage.STEP1)
    assert step1.object_roles == (
        EvidenceRole.SWSD_JUNCTION,
        EvidenceRole.DRIVEZONE,
    )
    assert tuple(step1.geometry_tokens.shape) == (2, 21)
    assert step1.geometry_tokens.data_ptr() != example.geometry_tokens.data_ptr()
    assert all(not role.value.startswith("RCSD") for role in step1.object_roles)
    assert tuple(step1.topology_edge_indices.shape) == (2, 1)


def test_surface_adds_only_rcsdintersection() -> None:
    firewall = StageFirewall()
    surface = firewall.build_view(_example(), EvidenceStage.SURFACE)
    assert surface.object_roles == (
        EvidenceRole.SWSD_JUNCTION,
        EvidenceRole.DRIVEZONE,
        EvidenceRole.RCSD_INTERSECTION,
    )
    assert EvidenceRole.RCSD_NODE not in surface.object_roles
    assert EvidenceRole.RCSD_ROAD not in surface.object_roles


def test_anchor_and_structured_views_preserve_all_raw_roles() -> None:
    firewall = StageFirewall()
    example = _example()
    anchor = firewall.build_view(example, EvidenceStage.ANCHOR)
    structured = firewall.build_view(example, EvidenceStage.STRUCTURED)
    assert anchor.object_roles == tuple(span.object_ref.role for span in example.object_spans)
    assert structured.object_roles == anchor.object_roles
    assert anchor.cache_key != structured.cache_key


def test_step1_gradient_has_no_path_to_rcsd_tokens() -> None:
    firewall = StageFirewall()
    example = _example(requires_grad=True)
    step1 = firewall.build_view(example, EvidenceStage.STEP1)
    step1.geometry_tokens.sum().backward()
    assert example.geometry_tokens.grad is not None
    assert torch.all(example.geometry_tokens.grad[:2] == 1)
    assert torch.all(example.geometry_tokens.grad[2:] == 0)


def test_stage_cache_key_is_content_and_stage_specific() -> None:
    firewall = StageFirewall()
    first = firewall.build_view(_example(), EvidenceStage.STEP1)
    second = firewall.build_view(_example(), EvidenceStage.STEP1)
    surface = firewall.build_view(_example(), EvidenceStage.SURFACE)
    assert first.cache_key == second.cache_key
    assert first.cache_key != surface.cache_key
