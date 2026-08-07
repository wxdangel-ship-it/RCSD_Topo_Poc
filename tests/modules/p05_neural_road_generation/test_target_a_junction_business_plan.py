from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_business_plan import (
    WILDCARD,
    BusinessPlanTemplate,
    business_plan_targets,
    decode_business_plan_tasks,
)
from tests.modules.p05_neural_road_generation.test_target_a_junction_joint_network import (
    _batch,
)


def test_business_plan_preserves_unknown_as_wildcard_and_abstain() -> None:
    batch = _batch()
    batch.task_masks["junctionization_action"][1] = False
    full = BusinessPlanTemplate(tuple(0 for _ in batch.task_labels))
    partial_values = tuple(
        WILDCARD if task == "junctionization_action" else 0
        for task in batch.task_labels
    )
    partial = BusinessPlanTemplate(partial_values)
    catalog = (full, partial)
    assert business_plan_targets(batch, catalog).tolist() == [0, 1]

    logits = torch.tensor([[5.0, 0.0], [0.0, 5.0]])
    predictions, requires_abstain = decode_business_plan_tasks(logits, catalog)
    assert predictions["junctionization_action"].tolist() == [0, WILDCARD]
    assert requires_abstain.tolist() == [False, True]
