from __future__ import annotations

import math

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_reranker import (
    BEAM_RELATIONAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_structured_energy import (
    StructuredEnergyWeights,
    proposal_energy,
)


def test_structured_energy_uses_only_declared_model_margins() -> None:
    features = [0.0] * BEAM_RELATIONAL_FEATURE_DIM
    features[5] = math.tanh(-2.0 / 10.0)
    features[6] = math.tanh(-0.5 / 3.0)
    features[18] = 0.4
    features[19] = 0.8
    features[119] = 0.3
    features[22] = 0.7
    features[123] = 0.2
    energy = proposal_energy(
        features,
        weights=StructuredEnergyWeights(
            total_log_probability=1.0,
            per_road_log_probability=2.0,
            membership_margin=3.0,
            ownership_margin=4.0,
            role_margin=5.0,
        ),
    )
    assert abs(
        energy
        - (
            -2.0
            + 2.0 * -0.5
            + 3.0 * 0.4
            + 4.0 * 0.5
            + 5.0 * 0.5
        )
    ) < 1e-6
