from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_models import (
    SchemeAP1Candidate,
    SchemeAP1CandidateConfig,
    SchemeAP1OOFConfig,
)


def test_candidate_contract_rejects_truth_and_coordinate_features() -> None:
    common = dict(
        case_key="T10:x",
        family="T10",
        business_id="x",
        object_type="SEGMENT",
        object_id="s1",
        group_id="g1",
        candidate_id="c1",
        candidate_target="KEEP_SWSD",
        target_kind="ROAD",
        target_payload=("r1",),
        source_kinds=("SWSD_IDENTITY",),
        object_tokens=("OBJECT:SEGMENT",),
        candidate_tokens=("OPTION:KEEP_SWSD",),
        context_tokens=("CONTEXT_JUNCTION_COUNT:2",),
        numeric_features=(0.0,) * 8,
        payload_artifacts=(),
    )
    with pytest.raises(ValueError, match="truth-free"):
        SchemeAP1Candidate(**common, truth_derived=True)
    with pytest.raises(ValueError, match="absolute coordinates"):
        SchemeAP1Candidate(**common, absolute_coordinate_feature_count=1)


def test_configs_validate_run_and_parameter_bounds() -> None:
    with pytest.raises(ValueError, match="run_id"):
        SchemeAP1CandidateConfig(Path("b"), Path("p"), Path("o"), "")
    with pytest.raises(ValueError, match="parameter count"):
        SchemeAP1OOFConfig(
            Path("d"),
            Path("c"),
            Path("b"),
            Path("o"),
            "run",
            min_parameter_count=10,
            max_parameter_count=9,
        )
